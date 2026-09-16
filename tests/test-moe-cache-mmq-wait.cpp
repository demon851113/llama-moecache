#include "test-moe-cache.h"

// Regression test for the staging-ready wait inside mul_mat_q (use_x_map path).
//
// The kernel waits for the copy stream to publish x_stage_ready[wait_class - 1] before it reads
// an expert that is still being staged. Without a bound on that wait, a producer that never
// signals (failed copy, lost event, crashed helper) leaves the kernel spinning forever: the GPU
// is stuck, the host sees no error, and the only way out is to kill the process. This test
// launches the kernel against a ready flag that is never set and requires that
//   1. the kernel returns on its own within the probe deadline, and
//   2. the context reports the fault so graph_compute can fail instead of returning garbage.
// A ready flag that is already set must still run to completion without a fault.
//
// The ready flag lives in mapped host memory so the test can release a hung kernel by hand
// before tearing down if the bound is ever lost again.

namespace {

struct mmq_wait_fixture {
    static constexpr int64_t N_EMBD = 512;
    static constexpr int64_t N_FF = 128;
    static constexpr int64_t N_EXPERTS = 2;
    static constexpr int64_t N_USED = 2;
    static constexpr int64_t N_TOKENS = 4;

    ggml_backend_t backend = nullptr;
    ggml_context * ctx = nullptr;
    ggml_backend_buffer_t buffer = nullptr;
    ggml_tensor * src0 = nullptr;
    ggml_tensor * src1 = nullptr;
    ggml_tensor * ids = nullptr;
    ggml_tensor * dst = nullptr;
    int32_t * source_map = nullptr;
    int32_t * wait_class = nullptr;
    uint32_t * ready_host = nullptr;
    uint32_t * ready_dev = nullptr;

    explicit mmq_wait_fixture(int device) {
        backend = ggml_backend_cuda_init(device);
        CHECK(backend != nullptr);

        ggml_init_params params = { 8 * ggml_tensor_overhead(), nullptr, true };
        ctx = ggml_init(params);
        CHECK(ctx != nullptr);
        src0 = ggml_new_tensor_3d(ctx, GGML_TYPE_Q8_0, N_EMBD, N_FF, N_EXPERTS);
        src1 = ggml_new_tensor_3d(ctx, GGML_TYPE_F32, N_EMBD, N_USED, N_TOKENS);
        ids = ggml_new_tensor_2d(ctx, GGML_TYPE_I32, N_USED, N_TOKENS);
        dst = ggml_new_tensor_3d(ctx, GGML_TYPE_F32, N_FF, N_USED, N_TOKENS);
        buffer = ggml_backend_alloc_ctx_tensors(ctx, backend);
        CHECK(buffer != nullptr);

        std::vector<uint8_t> zeros(ggml_nbytes(src0), 0);
        ggml_backend_tensor_set(src0, zeros.data(), 0, zeros.size());
        std::vector<float> input(ggml_nelements(src1), 1.0f);
        ggml_backend_tensor_set(src1, input.data(), 0, ggml_nbytes(src1));
        std::vector<int32_t> routes(ggml_nelements(ids));
        for (size_t i = 0; i < routes.size(); ++i) {
            routes[i] = static_cast<int32_t>(i % N_EXPERTS);
        }
        ggml_backend_tensor_set(ids, routes.data(), 0, ggml_nbytes(ids));

        // Every expert maps onto the primary source (below the split) and waits on class 1.
        const int32_t map[N_EXPERTS] = { 0, 1 };
        const int32_t classes[N_EXPERTS] = { 1, 1 };
        CUDA_OK(cudaMalloc(&source_map, sizeof(map)));
        CUDA_OK(cudaMalloc(&wait_class, sizeof(classes)));
        CUDA_OK(cudaMemcpy(source_map, map, sizeof(map), cudaMemcpyHostToDevice));
        CUDA_OK(cudaMemcpy(wait_class, classes, sizeof(classes), cudaMemcpyHostToDevice));

        void * host = nullptr;
        CUDA_OK(cudaHostAlloc(&host, sizeof(uint32_t), cudaHostAllocMapped));
        ready_host = static_cast<uint32_t *>(host);
        *ready_host = 0;
        void * dev = nullptr;
        CUDA_OK(cudaHostGetDevicePointer(&dev, host, 0));
        ready_dev = static_cast<uint32_t *>(dev);
    }

    // 0 = finished, 1 = still running after the deadline.
    int probe(int timeout_ms, int * fault) {
        return ggml_cuda_mul_mat_q_mapped_probe_for_test(
            backend, src0, src1, ids, dst, source_map, N_EXPERTS, wait_class, ready_dev, timeout_ms, fault);
    }

    void release_and_drain() {
        *static_cast<volatile uint32_t *>(ready_host) = 1;
        ggml_backend_synchronize(backend);
    }

    ~mmq_wait_fixture() {
        ggml_backend_synchronize(backend);
        CUDA_OK(cudaFreeHost(ready_host));
        CUDA_OK(cudaFree(wait_class));
        CUDA_OK(cudaFree(source_map));
        ggml_backend_buffer_free(buffer);
        ggml_free(ctx);
        ggml_backend_free(backend);
    }
};

} // namespace

void test_mmq_stage_wait_timeout(int device) {
    // The device-side bound is 4 s; give the probe plenty of slack on top of that.
    constexpr int PROBE_TIMEOUT_MS = 20000;

    {
        mmq_wait_fixture fixture(device);
        int fault = -1;
        const int status = fixture.probe(PROBE_TIMEOUT_MS, &fault);
        if (status == 1) {
            fprintf(stderr, "FAIL %s:%d  mul_mat_q kept spinning on an unsignalled stage_ready flag for %d ms\n",
                __FILE__, __LINE__, PROBE_TIMEOUT_MS);
            fixture.release_and_drain();
            std::exit(1);
        }
        CHECK(status == 0);
        CHECK(fault == 1);
    }

    {
        mmq_wait_fixture fixture(device);
        *static_cast<volatile uint32_t *>(fixture.ready_host) = 1;
        int fault = -1;
        const int status = fixture.probe(PROBE_TIMEOUT_MS, &fault);
        CHECK(status == 0);
        CHECK(fault == 0);
    }
}
