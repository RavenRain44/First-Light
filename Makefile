# Requires GNU make (on Windows, use the equivalent npm scripts: npm run setup / dev / test).
.PHONY: setup dev api web test history demo

setup:
	npm install --no-audit --no-fund
	node scripts/setup.mjs

dev:
	npm run dev

api:
	npm run dev:api

web:
	npm run dev:web

test:
	npm test

history:
	npm run build:history

demo:
	DEMO_MODE=true npm run dev
