"""
Telegram MCP Server - FastMCP Cloud Edition

Provides Telegram bot functionality through MCP protocol.
Includes tools for messaging admin and scheduling daily messages.
"""

import os
import httpx
from fastmcp import FastMCP

# Get configuration from environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

# Create MCP server
mcp = FastMCP("Telegram MCP Server")

# In-memory storage for scheduled messages (for FastMCP Cloud)
# Note: This will reset on deployment. For persistence, use FastMCP Cloud's storage features
scheduled_messages = []


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


@mcp.tool
async def message_admin(text: str) -> dict:
    """
    Send a message to the admin chat via Telegram.

    Args:
        text: The message text to send

    Returns:
        dict with success status or error message
    """
    if not TELEGRAM_BOT_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN not configured in environment"}

    if not ADMIN_CHAT_ID:
        return {"error": "ADMIN_CHAT_ID not configured in environment"}

    result = await send_telegram_message(TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID, text)

    if "error" in result:
        return result

    return {"success": True, "message": "Message sent to admin"}


@mcp.tool
def message_admin_scheduled(message: str) -> dict:
    """
    Add a message to the scheduled messages list (to be sent to admin later).

    Args:
        message: The message to schedule

    Returns:
        dict with success status
    """
    scheduled_messages.append(message)
    return {
        "success": True,
        "message": f"Message scheduled. Total scheduled: {len(scheduled_messages)}"
    }


@mcp.tool
def list_scheduled_messages() -> dict:
    """
    List all scheduled messages.

    Returns:
        dict with list of scheduled messages
    """
    return {
        "count": len(scheduled_messages),
        "messages": scheduled_messages
    }


@mcp.tool
async def send_all_scheduled_messages() -> dict:
    """
    Send all scheduled messages to admin and clear the list.

    Returns:
        dict with count of messages sent
    """
    if not scheduled_messages:
        return {"success": False, "message": "No messages scheduled"}

    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        return {"error": "Telegram credentials not configured"}

    sent_count = 0
    errors = []

    for message in scheduled_messages[:]:  # Create a copy to iterate
        result = await send_telegram_message(TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID, message)

        if "error" not in result:
            scheduled_messages.remove(message)
            sent_count += 1
        else:
            errors.append({"message": message, "error": result.get("error")})

    return {
        "success": True,
        "sent_count": sent_count,
        "remaining": len(scheduled_messages),
        "errors": errors if errors else None
    }


@mcp.resource("telegram://config")
def telegram_config() -> str:
    """Get Telegram configuration status"""
    return f"""Telegram MCP Server Configuration:
- Bot Token: {'✓ Configured' if TELEGRAM_BOT_TOKEN else '✗ Not configured'}
- Admin Chat ID: {'✓ Configured' if ADMIN_CHAT_ID else '✗ Not configured'}
- Scheduled Messages: {len(scheduled_messages)}
"""


@mcp.prompt("notify_admin")
def notify_admin_prompt(message: str) -> str:
    """Create a prompt to notify the admin with a message"""
    return f"Please send the following message to the admin: {message}"
