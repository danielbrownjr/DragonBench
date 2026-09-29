#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DB_RUN_ID_LEN 33
#define DB_HOST_LEN 254
#define DB_EVENT_CAPACITY 64
#define DB_EVENT_JSON_LEN 640

typedef enum {
    DB_BOOT,
    DB_IDLE,
    DB_WIFI_ASSOCIATED_IDLE,
    DB_NET_TX,
    DB_NET_RX,
    DB_NET_BIDIRECTIONAL,
    DB_CPU_STRESS,
    DB_FLASH_WRITE,
    DB_NVS_WRITE,
    DB_OTA_PARTITION_WRITE,
    DB_CONTROLLED_REBOOT,
    DB_FAN_PWM_HOLD, // bench stimulus; supported only in the fan-characterization profile
    DB_WORKLOAD_COUNT
} db_workload_t;

typedef enum { DB_RUN_IDLE, DB_RUN_RUNNING, DB_RUN_ABORTING, DB_RUN_COMPLETE } db_run_state_t;

typedef struct {
    db_workload_t workload;
    uint32_t duration_ms;
    uint32_t rate_bps;
    uint16_t port;
    char host[DB_HOST_LEN];
    // FAN_PWM_HOLD only. Zero-initialized requests carry no fan parameters.
    bool pwm_hz_set;
    bool sink_duty_set;
    uint32_t pwm_hz;
    uint16_t sink_duty_tenths_pct;
} db_run_request_t;

typedef struct {
    char run_id[DB_RUN_ID_LEN];
    db_run_request_t request;
    db_run_state_t state;
    bool abort_requested;
    char result[16];
    uint64_t started_ms;
    uint64_t ended_ms;
} db_run_t;

typedef struct {
    uint64_t seq;
    char json[DB_EVENT_JSON_LEN];
} db_event_t;

const char *db_workload_name(db_workload_t workload);
bool db_workload_parse(const char *name, db_workload_t *out);
bool db_workload_supported(db_workload_t workload);
bool db_request_validate(const db_run_request_t *request, char *error, size_t error_len);
void db_run_begin(db_run_t *run, const db_run_request_t *request, const char *run_id, uint64_t now_ms);
bool db_run_abort(db_run_t *run, const char *run_id);
void db_run_finish(db_run_t *run, const char *result, uint64_t now_ms);
// Whether the status light may show ready (green): the device has reached its
// ready state, no run is in progress, and the last run, if any, passed and is
// not a CONTROLLED_REBOOT about to restart. Anything else keeps it off.
bool db_status_ready(bool device_ready, const db_run_t *run);
