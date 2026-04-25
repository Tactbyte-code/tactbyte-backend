module.exports = {
  apps: [{
    name: "python-app",
    script: ".venv/bin/uvicorn",
    args: "src.main:app --port 8080",
    interpreter: "none",
    autorestart: true,
    watch: false
  }]
};