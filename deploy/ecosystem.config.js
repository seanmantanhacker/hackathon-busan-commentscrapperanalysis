// pm2 process definition for the SNS Listening dashboard.
//
//   pm2 start deploy/ecosystem.config.js
//   pm2 save            # persist across reboots (after `pm2 startup` once)
//   pm2 logs sns-listening
//
// Edit `cwd` and `interpreter` below to match the actual paths on the server
// (interpreter should point at the venv's python, not the system python, so
// it sees the installed packages from requirements.txt).
module.exports = {
  apps: [
    {
      name: "sns-listening",
      script: "serve.py",
      interpreter: "/var/www/hackathon-busan-commentscrapperanalysis/venv/bin/python3",
      cwd: "/var/www/hackathon-busan-commentscrapperanalysis",
      args: "--no-browser --port 3333",
      env: {
        PYTHONUNBUFFERED: "1",
      },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
    },
  ],
};
