/* ============================================================================
   orderbook.c  --  Stock Market Order Matching Engine (pure C core)
   ----------------------------------------------------------------------------
   Implements, exactly as specified:
     - Bid & Ask priority "queues": price levels kept in sorted pointer arrays
       (bids descending by price = best bid at index 0, asks ascending by
       price = best ask at index 0). This is the "sorted array" alternative
       to a binary heap mentioned in the spec, chosen so that price-level
       addresses never move (each PriceLevel is individually malloc'd and the
       arrays only ever reorder POINTERS), which keeps the order index valid.
     - Per-price FIFO queues: each PriceLevel owns a doubly linked list of
       Orders; new orders are appended at the tail and matched from the head,
       giving strict time priority within a price.
     - Matching loop: while best_bid >= best_ask (or a market order is being
       filled), match the front orders of both sides, reduce quantities,
       emit a Trade, and physically remove any order whose remaining qty
       hits zero (and drop the price level once its queue is empty).
     - Order index: a fixed-size hash table (chained) mapping order_id ->
       {Order*, side, PriceLevel*} for O(1) average cancel/modify, instead of
       scanning the book.
     - Event log: every accept / cancel / trade is appended to a growable
       in-memory array (and can be dumped to a file) for later analysis.

   Build targets (see build.sh):
     - liborderbook.so   : shared library consumed by app/engine_bridge.py
     - orderbook_cli     : standalone console demo (-DBUILD_CLI)
   ==========================================================================*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdarg.h>

/* ---------------------------------------------------------------------- */
/* Public constants                                                        */
/* ---------------------------------------------------------------------- */
#define SIDE_BUY   0
#define SIDE_SELL  1

#define TYPE_LIMIT  0
#define TYPE_MARKET 1

#define MAX_LEVELS   1024
#define INDEX_BUCKETS 4096

/* ---------------------------------------------------------------------- */
/* Core data structures                                                    */
/* ---------------------------------------------------------------------- */

typedef struct Order {
    int id;
    int side;           /* SIDE_BUY / SIDE_SELL               */
    int type;           /* TYPE_LIMIT / TYPE_MARKET            */
    double price;       /* resting price (0 for filled market) */
    int qty;            /* original quantity                   */
    int remaining;      /* quantity still open                 */
    long seq;           /* monotonic arrival sequence (time priority) */
    struct Order *prev, *next;  /* FIFO linkage within a PriceLevel   */
} Order;

typedef struct PriceLevel {
    double price;
    Order *head, *tail; /* FIFO queue of orders resting at this price */
    int order_count;
} PriceLevel;

typedef struct IndexNode {
    int id;
    Order *order;
    PriceLevel *level;  /* which level the order currently lives in   */
    int side;
    struct IndexNode *next;
} IndexNode;

typedef struct {
    int trade_id;
    int buy_id;
    int sell_id;
    double price;
    int qty;
    long seq;
} Trade;

typedef struct {
    long seq;
    char type[16];     /* "ACCEPT", "CANCEL", "TRADE", "REJECT" */
    char detail[160];
} EventLogEntry;

/* ---------------------------------------------------------------------- */
/* Global book state                                                       */
/* ---------------------------------------------------------------------- */

static PriceLevel *g_bids[MAX_LEVELS];   /* sorted DESC by price (best=0) */
static int g_bid_count = 0;
static PriceLevel *g_asks[MAX_LEVELS];   /* sorted ASC  by price (best=0) */
static int g_ask_count = 0;

static IndexNode *g_index[INDEX_BUCKETS];

static int g_next_order_id = 1;
static int g_next_trade_id = 1;
static long g_seq_counter = 0;

static Trade *g_trades = NULL;
static int g_trade_count = 0;
static int g_trade_cap = 0;

static EventLogEntry *g_events = NULL;
static int g_event_count = 0;
static int g_event_cap = 0;

/* ---------------------------------------------------------------------- */
/* Small growable-array / string-buffer helpers                           */
/* ---------------------------------------------------------------------- */

typedef struct {
    char *data;
    size_t len;
    size_t cap;
} StrBuf;

static void sb_init(StrBuf *b) {
    b->cap = 256;
    b->data = (char *)malloc(b->cap);
    b->data[0] = '\0';
    b->len = 0;
}

static void sb_append(StrBuf *b, const char *s) {
    size_t add = strlen(s);
    while (b->len + add + 1 > b->cap) {
        b->cap *= 2;
        b->data = (char *)realloc(b->data, b->cap);
    }
    memcpy(b->data + b->len, s, add + 1);
    b->len += add;
}

static void sb_appendf(StrBuf *b, const char *fmt, ...) {
    char tmp[256];
    va_list args;
    va_start(args, fmt);
    vsnprintf(tmp, sizeof(tmp), fmt, args);
    va_end(args);
    sb_append(b, tmp);
}

/* ---------------------------------------------------------------------- */
/* Event log                                                                */
/* ---------------------------------------------------------------------- */

static void log_event(const char *type, const char *fmt, ...) {
    if (g_event_count >= g_event_cap) {
        g_event_cap = g_event_cap ? g_event_cap * 2 : 256;
        g_events = (EventLogEntry *)realloc(g_events, g_event_cap * sizeof(EventLogEntry));
    }
    EventLogEntry *e = &g_events[g_event_count++];
    e->seq = ++g_seq_counter;
    strncpy(e->type, type, sizeof(e->type) - 1);
    e->type[sizeof(e->type) - 1] = '\0';

    char tmp[160];
    va_list args;
    va_start(args, fmt);
    vsnprintf(tmp, sizeof(tmp), fmt, args);
    va_end(args);
    strncpy(e->detail, tmp, sizeof(e->detail) - 1);
    e->detail[sizeof(e->detail) - 1] = '\0';
}

/* ---------------------------------------------------------------------- */
/* Order index (hash table, chained)                                       */
/* ---------------------------------------------------------------------- */

static int hash_id(int id) {
    unsigned int h = (unsigned int)id * 2654435761u;
    return (int)(h % INDEX_BUCKETS);
}

static void index_put(int id, Order *order, PriceLevel *level, int side) {
    int b = hash_id(id);
    IndexNode *n = (IndexNode *)malloc(sizeof(IndexNode));
    n->id = id;
    n->order = order;
    n->level = level;
    n->side = side;
    n->next = g_index[b];
    g_index[b] = n;
}

static IndexNode *index_find(int id) {
    int b = hash_id(id);
    for (IndexNode *n = g_index[b]; n; n = n->next)
        if (n->id == id) return n;
    return NULL;
}

static void index_remove(int id) {
    int b = hash_id(id);
    IndexNode *prev = NULL, *n = g_index[b];
    while (n) {
        if (n->id == id) {
            if (prev) prev->next = n->next; else g_index[b] = n->next;
            free(n);
            return;
        }
        prev = n;
        n = n->next;
    }
}

/* ---------------------------------------------------------------------- */
/* Price level management (sorted pointer arrays)                          */
/* ---------------------------------------------------------------------- */

/* Returns existing level at `price`, or creates+inserts a new one keeping
   the array sorted (DESC for bids, ASC for asks). O(n) insert, fine for a
   simulated / teaching-scale book; addresses of PriceLevel structs never
   move, only the pointers in the array are shuffled. */
static PriceLevel *find_or_create_level(int side, double price) {
    PriceLevel **arr = (side == SIDE_BUY) ? g_bids : g_asks;
    int *count = (side == SIDE_BUY) ? &g_bid_count : &g_ask_count;

    int lo = 0, hi = *count - 1, pos = *count;
    /* linear scan is sufficient at demo scale and keeps the comparison
       logic for both "greater" (bids) and "lesser" (asks) orderings simple */
    for (int i = 0; i < *count; i++) {
        if (arr[i]->price == price) return arr[i];
        if (side == SIDE_BUY  && price > arr[i]->price) { pos = i; break; }
        if (side == SIDE_SELL && price < arr[i]->price) { pos = i; break; }
    }
    (void)lo; (void)hi;

    if (*count >= MAX_LEVELS) return NULL; /* book full, extremely unlikely */

    PriceLevel *lvl = (PriceLevel *)malloc(sizeof(PriceLevel));
    lvl->price = price;
    lvl->head = lvl->tail = NULL;
    lvl->order_count = 0;

    for (int i = *count; i > pos; i--) arr[i] = arr[i - 1];
    arr[pos] = lvl;
    (*count)++;
    return lvl;
}

static void remove_level_if_empty(int side, PriceLevel *lvl) {
    if (lvl->order_count > 0) return;
    PriceLevel **arr = (side == SIDE_BUY) ? g_bids : g_asks;
    int *count = (side == SIDE_BUY) ? &g_bid_count : &g_ask_count;
    for (int i = 0; i < *count; i++) {
        if (arr[i] == lvl) {
            for (int j = i; j < *count - 1; j++) arr[j] = arr[j + 1];
            (*count)--;
            free(lvl);
            return;
        }
    }
}

/* ---------------------------------------------------------------------- */
/* FIFO queue helpers (per price level)                                    */
/* ---------------------------------------------------------------------- */

static void level_push_tail(PriceLevel *lvl, Order *o) {
    o->prev = lvl->tail;
    o->next = NULL;
    if (lvl->tail) lvl->tail->next = o; else lvl->head = o;
    lvl->tail = o;
    lvl->order_count++;
}

static void level_remove(PriceLevel *lvl, Order *o) {
    if (o->prev) o->prev->next = o->next; else lvl->head = o->next;
    if (o->next) o->next->prev = o->prev; else lvl->tail = o->prev;
    lvl->order_count--;
}

/* ---------------------------------------------------------------------- */
/* Trade recording                                                          */
/* ---------------------------------------------------------------------- */

static void record_trade(int buy_id, int sell_id, double price, int qty) {
    if (g_trade_count >= g_trade_cap) {
        g_trade_cap = g_trade_cap ? g_trade_cap * 2 : 256;
        g_trades = (Trade *)realloc(g_trades, g_trade_cap * sizeof(Trade));
    }
    Trade *t = &g_trades[g_trade_count++];
    t->trade_id = g_next_trade_id++;
    t->buy_id = buy_id;
    t->sell_id = sell_id;
    t->price = price;
    t->qty = qty;
    t->seq = ++g_seq_counter;
    log_event("TRADE", "buy=%d sell=%d price=%.2f qty=%d", buy_id, sell_id, price, qty);
}

/* ---------------------------------------------------------------------- */
/* The matching loop                                                        */
/* ---------------------------------------------------------------------- */

/* Matches resting bids against resting asks while they cross. Used after
   inserting a new LIMIT order (which may itself cross the book). */
static void match_book(void) {
    while (g_bid_count > 0 && g_ask_count > 0 &&
           g_bids[0]->price >= g_asks[0]->price) {
        PriceLevel *blvl = g_bids[0];
        PriceLevel *alvl = g_asks[0];
        Order *bo = blvl->head;
        Order *ao = alvl->head;
        if (!bo || !ao) break;

        int qty = (bo->remaining < ao->remaining) ? bo->remaining : ao->remaining;
        /* price-time priority: trade prints at the resting (earlier) order's
           price -- here we use the ask's price if it was resting first by
           sequence, otherwise the bid's; simplest convention for a book
           that can cross on either side: use the price of whichever side
           was already on the book (the maker) -- approximate with ask price
           for buy-initiated and bid price for sell-initiated via seq. */
        double trade_price = (bo->seq < ao->seq) ? bo->price : ao->price;

        record_trade(bo->id, ao->id, trade_price, qty);

        bo->remaining -= qty;
        ao->remaining -= qty;

        if (bo->remaining == 0) {
            level_remove(blvl, bo);
            index_remove(bo->id);
            free(bo);
        }
        if (ao->remaining == 0) {
            level_remove(alvl, ao);
            index_remove(ao->id);
            free(ao);
        }
        remove_level_if_empty(SIDE_BUY, blvl);
        remove_level_if_empty(SIDE_SELL, alvl);
    }
}

/* Executes a (non-resting) market order immediately against the opposite
   book, best price first, time priority within a level. Any unfilled
   remainder is NOT rested (IOC behaviour) and is logged as partially/ fully
   unfilled. Returns the quantity actually filled. */
static int execute_market(int side, int qty, int order_id) {
    int filled = 0;
    PriceLevel **opp = (side == SIDE_BUY) ? g_asks : g_bids;
    int *opp_count = (side == SIDE_BUY) ? &g_ask_count : &g_bid_count;
    int opp_side = (side == SIDE_BUY) ? SIDE_SELL : SIDE_BUY;

    while (qty > 0 && *opp_count > 0) {
        PriceLevel *lvl = opp[0];
        Order *resting = lvl->head;
        if (!resting) break;
        int m = (qty < resting->remaining) ? qty : resting->remaining;

        if (side == SIDE_BUY)
            record_trade(order_id, resting->id, lvl->price, m);
        else
            record_trade(resting->id, order_id, lvl->price, m);

        resting->remaining -= m;
        qty -= m;
        filled += m;

        if (resting->remaining == 0) {
            level_remove(lvl, resting);
            index_remove(resting->id);
            free(resting);
            remove_level_if_empty(opp_side, lvl);
        }
    }
    return filled;
}

/* ---------------------------------------------------------------------- */
/* Public API (exported for ctypes)                                        */
/* ---------------------------------------------------------------------- */

#if defined(_WIN32)
  #define OB_API __declspec(dllexport)
#else
  #define OB_API
#endif

OB_API void ob_init(void) {
    g_bid_count = g_ask_count = 0;
    memset(g_index, 0, sizeof(g_index));
    g_next_order_id = 1;
    g_next_trade_id = 1;
    g_seq_counter = 0;
    free(g_trades); g_trades = NULL; g_trade_count = g_trade_cap = 0;
    free(g_events); g_events = NULL; g_event_count = g_event_cap = 0;
    log_event("SYSTEM", "engine initialised");
}

/* Add a limit order. Returns the new order id. */
OB_API int ob_add_limit(int side, double price, int qty) {
    Order *o = (Order *)malloc(sizeof(Order));
    o->id = g_next_order_id++;
    o->side = side;
    o->type = TYPE_LIMIT;
    o->price = price;
    o->qty = qty;
    o->remaining = qty;
    o->seq = ++g_seq_counter;
    o->prev = o->next = NULL;

    int new_id = o->id; /* captured before match_book() can possibly free `o` */

    PriceLevel *lvl = find_or_create_level(side, price);
    if (!lvl) { free(o); log_event("REJECT", "book full id=%d", new_id); return -1; }
    level_push_tail(lvl, o);
    index_put(o->id, o, lvl, side);

    log_event("ACCEPT", "LIMIT id=%d side=%s price=%.2f qty=%d",
              new_id, side == SIDE_BUY ? "BUY" : "SELL", price, qty);

    match_book();
    return new_id;
}

/* Add a market order (immediate-or-cancel). Returns the new order id
   (the order itself is never rested; check filled qty via trades). */
OB_API int ob_add_market(int side, int qty) {
    int id = g_next_order_id++;
    long seq = ++g_seq_counter; (void)seq;
    log_event("ACCEPT", "MARKET id=%d side=%s qty=%d",
              id, side == SIDE_BUY ? "BUY" : "SELL", qty);
    int filled = execute_market(side, qty, id);
    if (filled < qty)
        log_event("CANCEL", "MARKET id=%d unfilled_remainder=%d (IOC)", id, qty - filled);
    return id;
}

/* Cancel a resting order by id. Returns 1 if cancelled, 0 if not found. */
OB_API int ob_cancel(int order_id) {
    IndexNode *n = index_find(order_id);
    if (!n) { log_event("REJECT", "cancel: id=%d not found", order_id); return 0; }
    level_remove(n->level, n->order);
    remove_level_if_empty(n->side, n->level);
    log_event("CANCEL", "id=%d side=%s price=%.2f remaining=%d",
              order_id, n->side == SIDE_BUY ? "BUY" : "SELL",
              n->order->price, n->order->remaining);
    free(n->order);
    index_remove(order_id);
    return 1;
}

/* ---- JSON dumps (caller must free with ob_free_string) ----------------- */

OB_API char *ob_get_book_json(int depth) {
    StrBuf b; sb_init(&b);
    sb_append(&b, "{\"bids\":[");
    int n = g_bid_count < depth ? g_bid_count : depth;
    for (int i = 0; i < n; i++) {
        PriceLevel *l = g_bids[i];
        sb_appendf(&b, "%s{\"price\":%.2f,\"qty\":%d,\"orders\":%d}",
                   i ? "," : "", l->price,
                   ({ int tot = 0; for (Order *o = l->head; o; o = o->next) tot += o->remaining; tot; }),
                   l->order_count);
    }
    sb_append(&b, "],\"asks\":[");
    n = g_ask_count < depth ? g_ask_count : depth;
    for (int i = 0; i < n; i++) {
        PriceLevel *l = g_asks[i];
        sb_appendf(&b, "%s{\"price\":%.2f,\"qty\":%d,\"orders\":%d}",
                   i ? "," : "", l->price,
                   ({ int tot = 0; for (Order *o = l->head; o; o = o->next) tot += o->remaining; tot; }),
                   l->order_count);
    }
    sb_append(&b, "]}");
    return b.data;
}

OB_API char *ob_get_trades_json(void) {
    StrBuf b; sb_init(&b);
    sb_append(&b, "[");
    for (int i = 0; i < g_trade_count; i++) {
        Trade *t = &g_trades[i];
        sb_appendf(&b, "%s{\"trade_id\":%d,\"buy_id\":%d,\"sell_id\":%d,\"price\":%.2f,\"qty\":%d,\"seq\":%ld}",
                   i ? "," : "", t->trade_id, t->buy_id, t->sell_id, t->price, t->qty, t->seq);
    }
    sb_append(&b, "]");
    return b.data;
}

OB_API char *ob_get_events_json(int max_n) {
    StrBuf b; sb_init(&b);
    sb_append(&b, "[");
    int start = (g_event_count > max_n) ? g_event_count - max_n : 0;
    for (int i = start; i < g_event_count; i++) {
        EventLogEntry *e = &g_events[i];
        /* detail may contain quotes/newlines only from our own sprintf calls above,
           which never emit them, so no escaping is required here */
        sb_appendf(&b, "%s{\"seq\":%ld,\"type\":\"%s\",\"detail\":\"%s\"}",
                   i > start ? "," : "", e->seq, e->type, e->detail);
    }
    sb_append(&b, "]");
    return b.data;
}

OB_API void ob_free_string(char *s) { free(s); }

OB_API int ob_trade_count(void) { return g_trade_count; }
OB_API int ob_event_count(void) { return g_event_count; }

/* ============================================================================
   Standalone console CLI (build with -DBUILD_CLI): demonstrates order-book
   depth, trade tape and simple performance counters, matching the spec's
   "Visualization & Metrics" requirement for the pure-C side.
   ==========================================================================*/
#ifdef BUILD_CLI

static void print_depth(void) {
    printf("\n================= ORDER BOOK DEPTH =================\n");
    printf("%-10s %-8s %-8s   %-10s %-8s %-8s\n", "BID px", "qty", "orders", "ASK px", "qty", "orders");
    int n = g_bid_count > g_ask_count ? g_bid_count : g_ask_count;
    if (n > 10) n = 10;
    for (int i = 0; i < n; i++) {
        char bbuf[32] = "", abuf[32] = "";
        int bq = 0, bo = 0, aq = 0, ao = 0;
        if (i < g_bid_count) {
            for (Order *o = g_bids[i]->head; o; o = o->next) bq += o->remaining;
            bo = g_bids[i]->order_count;
            snprintf(bbuf, sizeof(bbuf), "%.2f", g_bids[i]->price);
        }
        if (i < g_ask_count) {
            for (Order *o = g_asks[i]->head; o; o = o->next) aq += o->remaining;
            ao = g_asks[i]->order_count;
            snprintf(abuf, sizeof(abuf), "%.2f", g_asks[i]->price);
        }
        printf("%-10s %-8d %-8d   %-10s %-8d %-8d\n", bbuf, bq, bo, abuf, aq, ao);
    }
}

static void print_tape(int last_n) {
    printf("\n================= TRADE TAPE (last %d) =================\n", last_n);
    int start = g_trade_count > last_n ? g_trade_count - last_n : 0;
    for (int i = start; i < g_trade_count; i++) {
        Trade *t = &g_trades[i];
        printf("#%-5d BUY#%-4d SELL#%-4d  px=%-8.2f qty=%-6d\n",
               t->trade_id, t->buy_id, t->sell_id, t->price, t->qty);
    }
}

static void print_counters(clock_t start_clock) {
    double secs = (double)(clock() - start_clock) / CLOCKS_PER_SEC;
    printf("\n================= PERFORMANCE COUNTERS =================\n");
    printf("orders processed (incl. fills): %d\n", g_next_order_id - 1);
    printf("trades executed:                %d\n", g_trade_count);
    printf("events logged:                  %d\n", g_event_count);
    printf("active bid levels / ask levels: %d / %d\n", g_bid_count, g_ask_count);
    printf("wall time for this run:         %.4f s\n", secs);
}

int main(void) {
    clock_t start_clock = clock();
    ob_init();
    srand(42);

    printf("Stock Market Order Matching Engine -- C core console demo\n");

    /* Seed a synthetic order stream around a base price of 100.00 */
    double base = 100.00;
    for (int i = 0; i < 25; i++) {
        int side = rand() % 2;
        double offset = (rand() % 200 - 100) / 100.0; /* -1.00 .. +1.00 */
        double price = base + offset;
        if (price < 1) price = 1;
        int qty = 10 + rand() % 90;
        if (rand() % 10 == 0) {
            ob_add_market(side, qty);
        } else {
            ob_add_limit(side, price, qty);
        }
    }

    print_depth();
    print_tape(10);
    print_counters(start_clock);
    return 0;
}
#endif
