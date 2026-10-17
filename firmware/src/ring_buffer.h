// Lock-free single-producer/single-consumer byte ring (USB ISR -> main loop).
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>

namespace diag {

template <uint32_t N>
class SpscRing {
    static_assert(N > 0 && (N & (N - 1)) == 0, "size must be a power of two");

  public:
    // `start` only matters for tests of the free-running 32-bit index wrap-around.
    explicit SpscRing(uint32_t start = 0) : head_(start), tail_(start) {}

    // Producer side. Returns the number of bytes stored; the rest is counted as overflow.
    size_t Push(const uint8_t* data, size_t len) {
        uint32_t head = head_.load(std::memory_order_relaxed);
        const uint32_t tail = tail_.load(std::memory_order_acquire);
        size_t stored = 0;
        while(stored < len && head - tail < N) {
            buf_[head % N] = data[stored++];
            ++head;
        }
        head_.store(head, std::memory_order_release);
        if(stored < len)
            overflow_.fetch_add(static_cast<uint32_t>(len - stored), std::memory_order_relaxed);
        return stored;
    }

    // Consumer side.
    bool Pop(uint8_t& out) {
        const uint32_t tail = tail_.load(std::memory_order_relaxed);
        if(tail == head_.load(std::memory_order_acquire))
            return false;
        out = buf_[tail % N];
        tail_.store(tail + 1, std::memory_order_release);
        return true;
    }

    uint32_t Size() const {
        return head_.load(std::memory_order_acquire) - tail_.load(std::memory_order_acquire);
    }
    uint32_t Overflow() const { return overflow_.load(std::memory_order_relaxed); }
    static constexpr uint32_t Capacity() { return N; }

  private:
    uint8_t buf_[N] = {};
    std::atomic<uint32_t> head_;
    std::atomic<uint32_t> tail_;
    std::atomic<uint32_t> overflow_{0};
};

} // namespace diag
