# modal_app.py
import modal
from fastapi import FastAPI, HTTPException
import redis
from pydantic import BaseModel
import time
import subprocess
from typing import Optional

# Define the Modal app
app = modal.App("redis-example")

# Create an image that includes Redis
image = modal.Image.debian_slim().pip_install(["fastapi", "redis", "uvicorn"]).run_commands(
    "apt-get update",
    "apt-get install -y redis-server"
)

# Define the input model
class Item(BaseModel):
    key: str
    value: str

@app.cls(image=image)
class WebApp:
    def __init__(self):
        self.web_app = FastAPI()
        self.setup_routes()

    @modal.enter()
    def setup(self):
        # Start Redis server
        subprocess.Popen(["redis-server"])
        
        # Wait for Redis to be ready
        max_retries = 30
        for _ in range(max_retries):
            try:
                # Attempt to create Redis client and ping the server
                temp_client = redis.Redis(host='localhost', port=6379, db=0)
                temp_client.ping()
                self.redis_client = temp_client
                print("Successfully connected to Redis")
                return
            except (redis.exceptions.ConnectionError, redis.exceptions.ResponseError):
                print("Waiting for Redis to be ready...")
                time.sleep(1)
        
        raise Exception("Could not connect to Redis after multiple attempts")

    @modal.exit()
    def cleanup(self):
        if hasattr(self, "redis_client"):
            self.redis_client.close()

    def setup_routes(self):
        @self.web_app.post("/write")
        async def write_value(item: Item):
            try:
                self.redis_client.set(item.key, item.value)
                return {"message": f"Successfully wrote value for key: {item.key}"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.web_app.get("/read/{key}")
        async def read_value(key: str):
            try:
                value = self.redis_client.get(key)
                if value is None:
                    raise HTTPException(status_code=404, detail="Key not found")
                return {"key": key, "value": value.decode('utf-8')}
            except redis.exceptions.RedisError as e:
                raise HTTPException(status_code=500, detail=str(e))

    @modal.asgi_app()
    def serve(self):
        return self.web_app