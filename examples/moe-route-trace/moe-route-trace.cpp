// 路由追蹤：用排程器回呼攔下每層的 ffn_moe_topk（被選中的專家 id），逐 token 寫成文字檔，
// 供離線模擬專家快取策略（LRU / 頻率 / Belady 最佳）用。
// 用法：llama-moe-route-trace -m model.gguf [模型旗標同 llama-server] -p "提示" -n 300 [-o 輸出檔]
//       每行：step layer e1 e2 ... ek   （step 0 = 提示的每個 token 各一行，之後每 token 一個 step）
#include "arg.h"
#include "common.h"
#include "log.h"
#include "llama.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct trace_state {
    FILE * out = nullptr;
    int step = 0;
    std::vector<int32_t> buf;
};

static bool trace_cb(struct ggml_tensor * t, bool ask, void * user_data) {
    auto * st = (trace_state *) user_data;
    const bool is_topk = strncmp(t->name, "ffn_moe_topk", 12) == 0;
    if (ask) {
        return is_topk;
    }
    if (!is_topk || t->type != GGML_TYPE_I32) {
        return true;
    }
    int layer = -1;
    const char * dash = strrchr(t->name, '-');
    if (dash != nullptr) {
        layer = atoi(dash + 1);
    }
    const int64_t top_k = t->ne[0];
    const int64_t n_tok = t->ne[1];
    st->buf.resize((size_t) top_k * n_tok);
    ggml_backend_tensor_get(t, st->buf.data(), 0, st->buf.size() * sizeof(int32_t));
    for (int64_t i = 0; i < n_tok; ++i) {
        fprintf(st->out, "%d %d", st->step + (int) i, layer);
        for (int64_t k = 0; k < top_k; ++k) {
            fprintf(st->out, " %d", st->buf[i * top_k + k]);
        }
        fputc('\n', st->out);
    }
    return true;
}

int main(int argc, char ** argv) {
    std::string out_path = "route-trace.txt";
    std::vector<char *> args;
    for (int i = 0; i < argc; ++i) {
        if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
            out_path = argv[++i];
            continue;
        }
        args.push_back(argv[i]);
    }

    trace_state st;
    common_params params;
    params.n_predict = 200;
    common_init();
    if (!common_params_parse((int) args.size(), args.data(), params, LLAMA_EXAMPLE_COMMON)) {
        return 1;
    }
    st.out = fopen(out_path.c_str(), "w");
    if (st.out == nullptr) {
        LOG_ERR("cannot open %s\n", out_path.c_str());
        return 1;
    }

    llama_backend_init();
    llama_numa_init(params.numa);
    params.cb_eval = trace_cb;
    params.cb_eval_user_data = &st;
    params.warmup = false;

    auto llama_init = common_init_from_params(params);
    auto * model = llama_init->model();
    auto * ctx = llama_init->context();
    if (model == nullptr || ctx == nullptr) {
        LOG_ERR("init failed\n");
        return 1;
    }
    const llama_vocab * vocab = llama_model_get_vocab(model);
    std::vector<llama_token> tokens = common_tokenize(ctx, params.prompt, llama_vocab_get_add_bos(vocab), true);
    LOG_INF("prompt tokens = %zu, generating %d\n", tokens.size(), params.n_predict);

    st.step = 0;
    if (llama_decode(ctx, llama_batch_get_one(tokens.data(), (int32_t) tokens.size()))) {
        LOG_ERR("prompt decode failed\n");
        return 1;
    }
    st.step = (int) tokens.size();

    auto sparams = llama_sampler_chain_default_params();
    llama_sampler * smpl = llama_sampler_chain_init(sparams);
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());

    std::string text;
    for (int n = 0; n < params.n_predict; ++n) {
        llama_token id = llama_sampler_sample(smpl, ctx, -1);
        if (llama_vocab_is_eog(vocab, id)) {
            break;
        }
        text += common_token_to_piece(ctx, id);
        if (llama_decode(ctx, llama_batch_get_one(&id, 1))) {
            LOG_ERR("decode failed at %d\n", n);
            break;
        }
        st.step += 1;
    }
    fclose(st.out);
    LOG_INF("generated text head: %.200s\n", text.c_str());
    LOG_INF("trace written to %s (steps=%d)\n", out_path.c_str(), st.step);
    llama_sampler_free(smpl);
    llama_backend_free();
    return 0;
}
