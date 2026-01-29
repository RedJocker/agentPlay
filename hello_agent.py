from ollama import chat
from ollama import ChatResponse
from ollama import Message

messages= [
    {
        'role': 'user',
        'content': 'Hello, what is your name?',
    },
]

stream: generator = chat(
    model='qwen3:4b',
    messages=messages,
    stream=True,
)

thinking: str = ''
content: str = ''

chunk: ChatResponse
for chunk in stream:
    message : Message = chunk.message
    if message.thinking:
        if not thinking:
            print("Thinking:\n")
        print(message.thinking, end='', flush=True)
        thinking += message.thinking
    elif message.content:
        if not content:
            print("\n\nAnswer: \n")
        print(message.content, end='', flush=True)
        content += message.content

messages += {'role': 'assistant', 'thinking': thinking, 'content': content}
