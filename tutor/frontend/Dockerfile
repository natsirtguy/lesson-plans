# syntax=docker/dockerfile:1
FROM node:22-slim AS base

WORKDIR /srv

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
