import asyncio
import os
from ollama import chat, ChatResponse, Message, AsyncClient



# llm_port=8080
llm_port=11434
host="http://localhost:{0}".format(llm_port)
client = AsyncClient(host=host)


def hello_tool(model_name: str) -> str:
    """A tool used for greeting the user including the model name
    after usage use the return value as your response
    Args:
      model_name: The argument for The name of the model.

    Returns:
      A string with a greeting
    """
    return "Hello from hello_tool by " + model_name 

messages= [
    {
        'role': 'user',
        'content': 'Hello, what is your name?',
    },
]

tools = [hello_tool]

model = 'qwen3:4b'
# model = 'qwen3-vl:235b-cloud'   
# model = 'deepseek-v3.1:671b-cloud'
# model = 'gpt-oss:120b-cloud'
#model = 'nemotron-3-nano:30b-cloud'

async def make_call(model, tools, messages):
    print("make_call:\n")
    stream: async_generator = await client.chat(
        model=model,
        messages=messages,
        stream=True,
        tools=tools,
        think=True
    )
    
    thinking: str = ''
    content: str = ''
    tool_calls = []
    
    chunk: ChatResponse
    async for chunk in stream:
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
        elif message.tool_calls:
            print("\nTool_Call: ", end='')
            print(message.tool_calls)
            tool_calls.extend(message.tool_calls)
    print("\n")
    
    messages.append({
        'role': 'assistant',
        'thinking': thinking,
        'content': content,
        'tool_calls': tool_calls,
    })
    
    result: str = ''
    for call in tool_calls:
        if call.function.name == 'hello_tool':
            result = hello_tool(**call.function.arguments)
        else:
            result = 'There is no tool named ' + call.function.name
    if result:
        messages.append({
            'role': 'tool',
            'tool_name': call.function.name,
            'content': result,
        })
        await make_call(model, tools, messages)

asyncio.run(make_call(model, tools, messages))
