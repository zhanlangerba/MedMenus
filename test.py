from openai import OpenAI

client = OpenAI(api_key="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")

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ]
)

print(response.choices[0].message.content)