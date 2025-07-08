import os


def get_llm_prompt(prompt=None) -> str:
    if prompt is None or prompt.strip() == "":
        return os.environ.get("LLM_PROMPT", "Write a detailed caption for this image.")
    return prompt
