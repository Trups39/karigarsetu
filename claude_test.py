"""Quick check that your Anthropic API key works.

Run:  python claude_test.py
Needs: pip install anthropic python-dotenv
       ANTHROPIC_API_KEY=sk-ant-... in your .env file (same folder)
Cost:  a fraction of a cent (cheapest model, reply capped at 100 tokens)
"""
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

msg = client.messages.create(
    model="claude-haiku-5-5",   # cheapest model, good for testing
    max_tokens=400,             # caps the reply length, so the cost stays tiny
    messages=[{
        "role": "user",
        "content": "Size 8 Kapshi किती आहे? Reply in one short line.",
    }],
)

# The reply can contain a "thinking" block before the answer; print only the text.
text = "".join(block.text for block in msg.content if block.type == "text")
print("Claude says:", text or "(no text: all tokens went to thinking; raise max_tokens)")
print("Tokens used:", msg.usage.input_tokens, "in,", msg.usage.output_tokens, "out")