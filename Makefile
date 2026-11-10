.PHONY: api-docs
api-docs: ## Regenerate openapi.json, API.md reference and frontend/src/api/schema.d.ts
	cd backend && uv run python scripts/gen_api_docs.py
	cd frontend && npm run gen:api
