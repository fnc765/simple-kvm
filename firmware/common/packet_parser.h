#pragma once
#include <stdint.h>
#include <stdbool.h>

// ---------------------------------------------------------------------------
// Packet format:
//   [0xAA] [TYPE] [LEN] [PAYLOAD × LEN] [CRC-8-CCITT]
//   CRC-8-CCITT over TYPE + LEN + PAYLOAD (polynomial 0x07)
// ---------------------------------------------------------------------------

#define PKT_START      0xAAu
#define PKT_KEYBOARD   0x01u  // 8-byte HID Boot Keyboard Report
#define PKT_MOUSE      0x02u  // 5-byte HID Mouse Report
#define PKT_HEARTBEAT  0xFFu  // No payload (LEN=0)

#define PKT_LEN_KEYBOARD   8u
#define PKT_LEN_MOUSE      5u
#define PKT_LEN_HEARTBEAT  0u
#define PKT_MAX_PAYLOAD   16u  // Reject packets with LEN > this

// CRC-8-CCITT (polynomial 0x07)
uint8_t crc8_calc(const uint8_t *data, uint8_t len);

// Parser state machine states
typedef enum {
    PS_IDLE,
    PS_TYPE,
    PS_LEN,
    PS_PAYLOAD,
    PS_CHECKSUM
} ParserState;

// Completed packet
typedef struct {
    uint8_t type;
    uint8_t len;
    uint8_t payload[PKT_MAX_PAYLOAD];
} Packet;

// Parser context – zero-initialise before use
typedef struct {
    ParserState state;
    uint8_t     type;
    uint8_t     len;
    uint8_t     payload[PKT_MAX_PAYLOAD];
    uint8_t     offset;
    uint8_t     checksum;   // Running CRC-8 accumulator
    uint32_t    last_ms;    // Timestamp of last received byte (millis)
} PacketParser;

/** Fully zero-initialise the parser via memset (sets all fields to a safe initial state). Call once in setup(). */
void parser_init(PacketParser *p);

/**
 * Feed one byte into the parser.
 * Returns true (and fills *out) when a valid, checksum-verified packet
 * has been assembled.  Returns false otherwise.
 */
bool parser_feed(PacketParser *p, uint8_t byte, Packet *out);
