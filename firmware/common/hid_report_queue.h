#pragma once

#include <stdint.h>
#include <string.h>

namespace simple_kvm {

// Relative motion and wheel values are increments, not replaceable positions.
// Preserve every admitted report, including identical consecutive wheel ticks.
class HidReportQueue {
public:
    static constexpr uint8_t kCapacity = 32U;
    static constexpr uint8_t kMaxReportBytes = 8U;

    void clear()
    {
        head_ = 0U;
        count_ = 0U;
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

    uint8_t *front()
    {
        return count_ == 0U ? nullptr : reports_[head_];
    }

    void pop()
    {
        if (count_ == 0U) return;
        head_ = index(1U);
        --count_;
    }

    uint8_t size() const { return count_; }

private:
    uint8_t index(uint8_t offset) const
    {
        return static_cast<uint8_t>(
            (static_cast<uint16_t>(head_) + offset) % kCapacity);
    }

    uint8_t reports_[kCapacity][kMaxReportBytes]{};
    uint8_t head_ = 0U;
    uint8_t count_ = 0U;
};

}  // namespace simple_kvm
