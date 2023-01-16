FROM node:14.21.1-alpine

ENV HOST=127.0.0.1
ENV PORT=25565
ENV USERNAME=Steve
ENV BOX_WIDTH=500
ENV NUMBER_STEPS=10000

# get dependencies
COPY src/package.json package.json
RUN npm install --loglevel verbose

COPY src/worker_bot.js worker_bot.js

CMD node worker_bot.js