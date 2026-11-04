#pragma once

#include <stdint.h>
#include <string.h>

namespace simple_kvm {

// Keyboard reports use push(). Relative mouse queues use push_mouse(), which
// sums compatible increments and reserves one final button state on overflow.
class HidReportQueue {
public:
    static constexpr uint8_t kCapacity = 32U;
    static constexpr uint8_t kMaxReportBytes = 8U;

    enum class MousePushResult : uint8_t {
        kQueued,
        kStateOnly,  // latest buttons kept, but input history/data was lost
        kDropped,
    };

    void clear()
    {
        head_ = 0U;
        count_ = 0U;
        pending_mouse_state_ = false;
        last_mouse_buttons_ = 0U;
    }

    bool push(const uint8_t *report, uint8_t length)
    {
        if (report == nullptr || length == 0U || length > kMaxReportBytes ||
            count_ >= kCapacity) {
            return false;
        }
        memcpy(reports_[index(count_)], report, length);
        ++count_;
        return true;
    }

    MousePushResult push_mouse(const uint8_t *report, uint8_t length)
    {
        if (report == nullptr || length != 5U) return MousePushResult::kDropped;
        const bool buttons_changed = report[0] != last_mouse_buttons_;
        last_mouse_buttons_ = report[0];

        // A deferred button edge must precede all subsequently admitted input.
        if (pending_mouse_state_ && count_ < kCapacity) {
            push(pending_mouse_report_, 5U);
            pending_mouse_state_ = false;
        }
        if (!pending_mouse_state_) {
            if (count_ != 0U && merge_mouse_tail(report)) {
                return MousePushResult::kQueued;
            }
            if (push(report, length)) return MousePushResult::kQueued;
        }

        if (!buttons_changed) return MousePushResult::kDropped;

        // Keep all admitted wheel reports intact. The reserved control slot
        // guarantees a final release even when no FIFO slot can be freed.
        // Pathological button spam can replace this slot; report that loss.
        const bool replaced_state = pending_mouse_state_;
        pending_mouse_report_[0] = report[0];
        pending_mouse_state_ = true;
        const bool has_deltas = report[1] || report[2] || report[3] || report[4];
        return replaced_state || has_deltas
            ? MousePushResult::kStateOnly : MousePushResult::kQueued;
    }

    uint8_t *front()
    {
        if (count_ != 0U) return reports_[head_];
        return pending_mouse_state_ ? pending_mouse_report_ : nullptr;
    }

    void pop()
    {
        if (count_ == 0U) {
            pending_mouse_state_ = false;
            return;
        }
        head_ = index(1U);
        --count_;
    }

    uint8_t size() const
    {
        return static_cast<uint8_t>(count_ + (pending_mouse_state_ ? 1U : 0U));
    }

private:
    bool merge_mouse_tail(const uint8_t *report)
    {
        uint8_t *tail = reports_[index(static_cast<uint8_t>(count_ - 1U))];
        if (tail[0] != report[0]) return false;
        int16_t sums[4];
        for (uint8_t axis = 1U; axis < 5U; ++axis) {
            const int16_t before = static_cast<int8_t>(tail[axis]);
            const int16_t added = static_cast<int8_t>(report[axis]);
            // Opposite wheel directions are ordered events (e.g. at a page
            // boundary); never cancel them into a zero-net scroll report.
            if (axis >= 3U && ((before < 0 && added > 0) ||
                              (before > 0 && added < 0))) return false;
            sums[axis - 1U] = static_cast<int16_t>(before + added);
            if (sums[axis - 1U] < -127 || sums[axis - 1U] > 127) return false;
        }
        for (uint8_t axis = 1U; axis < 5U; ++axis) {
            tail[axis] = static_cast<uint8_t>(sums[axis - 1U]);
        }
        return true;
    }

    uint8_t index(uint8_t offset) const
    {
        return static_cast<uint8_t>(
            (static_cast<uint16_t>(head_) + offset) % kCapacity);
    }

    uint8_t reports_[kCapacity][kMaxReportBytes]{};
    uint8_t head_ = 0U;
    uint8_t count_ = 0U;
    uint8_t pending_mouse_report_[5]{};
    bool pending_mouse_state_ = false;
    uint8_t last_mouse_buttons_ = 0U;
};

}  // namespace simple_kvm
