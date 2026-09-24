// 微基準：pinned host → device 的三種搬法，量 GB/s（獨立於模型）
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#define CK(x) do{cudaError_t e=(x); if(e!=cudaSuccess){printf("CUDA err %s @%d\n",cudaGetErrorString(e),__LINE__); exit(1);} }while(0)

// A. 作者風格：grid-stride，每執行緒每輪 1 個 uint4 讀完就寫
__global__ void naive(const uint4* __restrict__ src, uint4* __restrict__ dst, size_t words){
    size_t i=(size_t)blockIdx.x*blockDim.x+threadIdx.x, s=(size_t)gridDim.x*blockDim.x;
    for(; i<words; i+=s) dst[i]=src[i];
}
// B. 展開 8：先發 8 個獨立讀，再寫
template<int U> __global__ void unrolled(const uint4* __restrict__ src, uint4* __restrict__ dst, size_t words){
    size_t base=((size_t)blockIdx.x*blockDim.x+threadIdx.x), s=(size_t)gridDim.x*blockDim.x;
    for(size_t i=base; i<words; i+=s*U){
        uint4 v[U];
        #pragma unroll
        for(int u=0;u<U;u++){ size_t j=i+u*s; v[u]= j<words? src[j]: make_uint4(0,0,0,0); }
        #pragma unroll
        for(int u=0;u<U;u++){ size_t j=i+u*s; if(j<words) dst[j]=v[u]; }
    }
}
int main(int argc,char**argv){
    size_t mb = argc>1? atoi(argv[1]):16; size_t bytes=mb<<20, words=bytes/16;
    void* h; CK(cudaHostAlloc(&h, bytes, cudaHostAllocMapped|cudaHostAllocPortable)); memset(h,1,bytes);
    uint4* hd; CK(cudaHostGetDevicePointer((void**)&hd,h,0));
    uint4* d; CK(cudaMalloc(&d, bytes));
    cudaEvent_t a,b; CK(cudaEventCreate(&a)); CK(cudaEventCreate(&b));
    int nsm; CK(cudaDeviceGetAttribute(&nsm, cudaDevAttrMultiProcessorCount, 0));
    auto time=[&](auto launch, const char* name){
        launch(); CK(cudaDeviceSynchronize()); // 暖身
        CK(cudaEventRecord(a)); for(int r=0;r<20;r++) launch(); CK(cudaEventRecord(b)); CK(cudaEventSynchronize(b));
        float ms; CK(cudaEventElapsedTime(&ms,a,b)); ms/=20;
        printf("  %-38s %7.3f ms  %6.1f GB/s\n", name, ms, bytes/ms/1e6);
    };
    printf("chunk=%zu MB  SM=%d\n", mb, nsm);
    for(int bps: {4, 8, 16}){
        int blocks=nsm*bps; char n1[64],n2[64],n3[64];
        snprintf(n1,64,"naive        blocks/SM=%d",bps); snprintf(n2,64,"unroll4      blocks/SM=%d",bps); snprintf(n3,64,"unroll8      blocks/SM=%d",bps);
        time([&]{ naive<<<blocks,256>>>(hd,d,words); }, n1);
        time([&]{ unrolled<4><<<blocks,256>>>(hd,d,words); }, n2);
        time([&]{ unrolled<8><<<blocks,256>>>(hd,d,words); }, n3);
    }
    time([&]{ CK(cudaMemcpyAsync(d,h,bytes,cudaMemcpyHostToDevice,0)); }, "cudaMemcpyAsync (copy engine)");
    return 0;
}
