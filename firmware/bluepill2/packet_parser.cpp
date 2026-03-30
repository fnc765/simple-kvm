#include "packet_parser.h"
#include <Arduino.h>

#define PARSER_TIMEOUT_MS 50u

void parser_init(PacketParser *p)
{
    memset(p, 0, sizeof(*p));
}

bool parser_feed(PacketParser *p, uint8_t b, Packet *out)
{
    uint32_t now = millis();

    if (p->state != PS_IDLE && (now - p->last_ms) > PARSER_TIMEOUT_MS) {
        p->state = PS_IDLE;
    }
    p->last_ms = now;

    // Re-sync only in PS_TYPE and PS_LEN states to avoid false resets
    // from payload bytes that happen to equal PKT_START (0xAA).
    if (b == PKT_START &&
        (p->state == PS_TYPE || p->state == PS_LEN)) {
        p->state    = PS_TYPE;
        p->checksum = 0;
        p->offset   = 0;
        return false;
    }

    switch (p->state) {
        case PS_IDLE:
            if (b == PKT_START) {
                p->state    = PS_TYPE;
                p->checksum = 0;
            }
            break;

        case PS_TYPE:
            p->type      = b;
            p->checksum ^= b;
            p->state     = PS_LEN;
            break;

        case PS_LEN:
            if (b > PKT_MAX_PAYLOAD) {
                p->state = PS_IDLE;
                break;
            }
            p->len       = b;
            p->checksum ^= b;
            p->offset    = 0;
            p->state     = (b == 0) ? PS_CHECKSUM : PS_PAYLOAD;
            break;

        case PS_PAYLOAD:
            p->payload[p->offset++]  = b;
            p->checksum             ^= b;
            if (p->offset >= p->len) {
                p->state = PS_CHECKSUM;
            }
            break;

        case PS_CHECKSUM:
            p->state = PS_IDLE;
            if (b == p->checksum) {
                out->type = p->type;
                out->len  = p->len;
                for (uint8_t i = 0; i < p->len; i++) {
                    out->payload[i] = p->payload[i];
                }
                return true;
            }
            break;
    }
    return false;
}
