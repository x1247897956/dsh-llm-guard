# LLM Guard v2 — 一键复现入口
#
#   make setup   安装依赖（uv 管理，Python 3.11）
#   make run     启动检测服务（127.0.0.1:8000）
#   make test    跑单元测试
#   make eval    跑评测（规则层 vs 规则+语义层），输出指标
#   make gate    评测门禁：指标低于 eval/baseline.json 即失败（CI 用）
#   make plugin-check  DSH 插件静态校验
#   make clean   清理缓存

SHELL := /bin/bash
PY := 3.12
UV := uv
VENV := .venv
SERVICE_DIR := service
EVAL_DIR := eval

# uv 缓存放到仓库内（可用环境变量覆盖）。某些受限环境无法写 ~/.cache/uv。
export UV_CACHE_DIR ?= $(CURDIR)/.scratch/uv-cache

# 语义层需要 DEEPSEEK_API_KEY；没有 key 时服务自动降级为纯规则版
-include $(SERVICE_DIR)/.env
export

.DEFAULT_GOAL := help
.PHONY: help setup run test eval eval-rules eval-semantic gate spotcheck spotcheck-score plugin-check lint clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## 安装依赖并生成 service/.env 模板
	$(UV) venv --python $(PY) $(VENV)
	$(UV) pip install --python $(VENV)/bin/python -r $(SERVICE_DIR)/requirements.txt
	$(UV) pip install --python $(VENV)/bin/python pytest httpx
	@test -f $(SERVICE_DIR)/.env || (cp .env.example $(SERVICE_DIR)/.env && echo "已生成 service/.env（语义层需填入 DEEPSEEK_API_KEY）")

run: ## 启动 FastAPI 检测服务
	$(VENV)/bin/python -m uvicorn service.main:app --host $${LLM_GUARD_HOST:-127.0.0.1} --port $${LLM_GUARD_PORT:-8000}

test: ## 单元测试
	$(VENV)/bin/python -m pytest $(SERVICE_DIR)/tests -q

eval: ## 一键评测：规则层 vs 规则+语义层（真实调用模型）
	$(VENV)/bin/python -m eval.runner --mode both --out $(EVAL_DIR)/results

eval-all: ## 一键评测：额外加上 semantic+exfil 档（凭据外泄意图）
	$(VENV)/bin/python -m eval.runner --mode all --out $(EVAL_DIR)/results

eval-rules: ## 只跑规则层（不消耗 API 额度）
	$(VENV)/bin/python -m eval.runner --mode rules --out $(EVAL_DIR)/results

eval-semantic: ## 只跑规则+语义层
	$(VENV)/bin/python -m eval.runner --mode rules+semantic --out $(EVAL_DIR)/results

gate: ## 评测门禁：与 eval/baseline.json 比对，掉线即退出码 1
	$(VENV)/bin/python -m eval.gate --results $(EVAL_DIR)/results --baseline $(EVAL_DIR)/baseline.json

spotcheck: ## 人工抽检：生成复核表（填完用 spotcheck-score 统计）
	$(VENV)/bin/python -m eval.spotcheck sheet --frac 0.25 --out $(EVAL_DIR)/results/spotcheck.csv

spotcheck-score: ## 人工抽检：统计一致率
	$(VENV)/bin/python -m eval.spotcheck score --sheet $(EVAL_DIR)/results/spotcheck.csv

plugin-check: ## DSH 插件静态校验（语法 + 契约）
	$(VENV)/bin/python -m eval.plugin_check

clean: ## 清理缓存与评测产物
	rm -rf $(VENV) .pytest_cache $(SERVICE_DIR)/__pycache__ $(SERVICE_DIR)/detectors/__pycache__ $(SERVICE_DIR)/tests/__pycache__ $(EVAL_DIR)/results/*.json $(EVAL_DIR)/results/*.md
