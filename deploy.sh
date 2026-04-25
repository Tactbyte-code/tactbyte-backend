#!/bin/bash
set -e

echo "Pulling latest code..."
git pull origin main

echo "Installing dependencies..."
uv sync --frozen --no-dev

echo "Reloading app..."
pm2 reload ecosystem.config.js || pm2 start ecosystem.config.js

echo "Saving PM2 state..."
pm2 save

echo "Deploy complete"