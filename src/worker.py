import httpx
import json
from workers import DurableObject, WorkerEntrypoint, Response
from mcp.server.fastmcp import FastMCP
import asgi


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> dict:
    """Utility function to send a message via Telegram Bot API"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "chat_id": chat_id,
            "text": text
        })

        if response.status_code != 200:
            return {"error": "Failed to send message", "status_code": response.status_code}

        return response.json()


async def send_message_to_admin(env, text: str) -> dict:
    """Utility function to send a message to admin"""
    bot_token = getattr(env, "TELEGRAM_BOT_TOKEN", None)
    admin_chat_id = getattr(env, "ADMIN_CHAT_ID", None)

    if not bot_token:
        return {"error": "TELEGRAM_BOT_TOKEN not configured"}

    if not admin_chat_id:
        return {"error": "ADMIN_CHAT_ID not configured"}

    return await send_telegram_message(bot_token, admin_chat_id, text)


class TelegramMCPServer(DurableObject):
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env
        self.mcp = FastMCP("Telegram MCP Server")

        # Initialize SQLite storage for daily message
        self.ctx.storage.sql.exec("""
            CREATE TABLE IF NOT EXISTS daily_message (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Commented out: This tool allows sending messages to arbitrary chat_ids.
        # An LLM with access to this could potentially send unwanted messages to any user/group.
        # Use message_admin() instead for restricted, admin-only messaging.
        # @self.mcp.tool()
        # async def send_message(chat_id: str, text: str) -> dict:
        #     """Send a message to a Telegram chat"""
        #     bot_token = getattr(env, "TELEGRAM_BOT_TOKEN", None)
        #
        #     if not bot_token:
        #         return {"error": "TELEGRAM_BOT_TOKEN not configured"}
        #
        #     return await send_telegram_message(bot_token, chat_id, text)

        @self.mcp.tool()
        async def message_admin(text: str) -> dict:
            """Send a message to the admin chat"""
            return await send_message_to_admin(env, text)

        @self.mcp.tool()
        def message_admin_scheduled(message: str) -> dict:
            """Add a daily message that will be sent to admin"""
            try:
                self.ctx.storage.sql.exec(
                    "INSERT INTO daily_message (message) VALUES (?)",
                    message
                )
                return {"success": True, "message": "Daily message added"}
            except Exception as e:
                return {"error": str(e)}

        self.app = self.mcp.sse_app()

    async def fetch(self, request):
        url = request.url

        # Handle daily message endpoint
        if "/send-daily-message" in url:
            return await self.send_daily_messages()

        return await asgi.fetch(self.app, request, self.env, self.ctx)

    async def send_daily_messages(self):
        """Send all daily messages from storage to admin"""
        try:
            # Get all messages from storage with their IDs
            cursor = self.ctx.storage.sql.exec(
                "SELECT id, message FROM daily_message"
            )

            rows = cursor.toArray().to_py()
            messages = [(row['id'], row['message']) for row in rows]

            if not messages:
                return Response(
                    json.dumps({"error": "No daily messages found in storage"}),
                    status=404,
                    headers={"Content-Type": "application/json"}
                )

            # Send all messages to admin
            sent_count = 0

            for message_id, message_text in messages:
                result = await send_message_to_admin(self.env, message_text)

                if "error" not in result:
                    # Delete the message from storage after successful send
                    self.ctx.storage.sql.exec(
                        "DELETE FROM daily_message WHERE id = ?",
                        message_id
                    )
                    sent_count += 1

            return Response(
                json.dumps({"success": True, "message": f"Sent {sent_count} daily messages"}),
                status=200,
                headers={"Content-Type": "application/json"}
            )
        except Exception as e:
            return Response(
                json.dumps({"error": str(e)}),
                status=500,
                headers={"Content-Type": "application/json"}
            )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # Create a Durable Object instance and forward all requests to it
        id = self.env.TELEGRAM_MCP.idFromName("telegram-bot")
        stub = self.env.TELEGRAM_MCP.get(id)
        return await stub.fetch(request)
