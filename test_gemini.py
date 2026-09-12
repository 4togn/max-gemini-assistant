import asyncio
from gemini_client import GeminiClient

async def test_gemini():
    client = GeminiClient()
    print(f"[+] Проверка запроса к модели: {client.model_name}")
    try:
        response = await client.generate_response("Реши уравнение x^2 - 5x + 6 = 0 с формулами LaTeX")
        print("[OK] Ответ получен успешно:")
        print(response[:300])
    except Exception as e:
        print(f"[FAIL] Ошибка запроса: {e}")

if __name__ == "__main__":
    asyncio.run(test_gemini())
