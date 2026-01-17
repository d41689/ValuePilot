FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source
COPY . .

# Build for production (optional, but good to verify it builds)
# Skipping 'npm run build' for now to speed up dev startup and avoid issues if local files are missing
# RUN npm run build 

EXPOSE 3000

CMD ["npm", "run", "dev"]