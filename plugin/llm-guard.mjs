// llm-guard.mjs — DSH 单文件工具插件
//
// 将 Python/LangChain 检测服务（LLM Guard）桥接为 DSH 的一个一等公民工具。
// 工具名 llm_guard_scan：输入一段 prompt/对话，返回风险报告。
//
// 依赖的 Python 服务默认监听 http://127.0.0.1:8000，可用 config.endpoint 覆盖。

import { defineTool } from "@deepseek-ai/dsh-tools";

const name = "llm-guard";
const inject = ["tools"];

// 插件级 config schema（经 cordis.patch.yml 的 config 传入）
const Config = {
  endpoint: "http://127.0.0.1:8000",
};

function apply(ctx, config) {
  const endpoint = (config && config.endpoint) || "http://127.0.0.1:8000";

  const tool = defineTool({
    name: "llm_guard_scan",
    description:
      "对一段 prompt 或对话文本做 LLM 安全检测，识别提示词注入、越狱绕过、敏感数据外泄三类风险。输入文本，返回风险报告（是否危险、风险类型、命中特征、判定依据）。",

    parameters: {
      text: {
        type: "string",
        description: "待检测的 prompt 或对话文本",
        required: true,
      },
    },

    output: {
      schema: {
        type: "object",
        properties: {
          input: { type: "string" },
          risky: { type: "boolean" },
          detections: {
            type: "array",
            items: {
              type: "object",
              properties: {
                risk_type: { type: "string" },
                is_risky: { type: "boolean" },
                reason: { type: "string" },
                matches: { type: "array", items: { type: "string" } },
              },
              required: ["risk_type", "is_risky", "reason", "matches"],
            },
          },
        },
        required: ["input", "risky", "detections"],
      },

      render(args, value) {
        if (value.risky) {
          const risks = value.detections
            .filter((d) => d.is_risky)
            .map((d) => `${d.risk_type}: ${d.reason}`)
            .join("; ");
          return [{ type: "text", text: `检测到风险：${risks}` }];
        }
        return [{ type: "text", text: "未检测到风险。" }];
      },
    },

    async execute(args, exec) {
      const resp = await fetch(`${endpoint}/scan`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: args.text }),
        signal: exec.signal,
      });

      if (!resp.ok) {
        throw new Error(`LLM Guard 服务返回 ${resp.status}: ${await resp.text()}`);
      }

      return await resp.json();
    },
  });

  ctx.tools.register(tool);
}

export { name, inject, Config, apply };
