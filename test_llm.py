"""
独立测试脚本：验证 LM Studio OpenAI 兼容 API 调用是否正常。
使用方法：
  python test_llm.py                           # 使用默认地址 http://localhost:1234
  python test_llm.py http://192.168.1.100:1234 # 指定局域网地址
"""

import asyncio
import json
import re
import sys

# ---------- 纯函数测试（无需网络） ----------

def _parse_tag_response(text: str) -> list[str]:
    """从 LLM 返回文本中提取 JSON 数组。"""
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [str(t).strip() for t in result if str(t).strip()]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(t).strip() for t in result if str(t).strip()]
        except json.JSONDecodeError:
            pass

    return []


def test_parse_tag_response():
    """测试标签解析函数。"""
    print("=" * 50)
    print("测试 1: _parse_tag_response 纯函数")
    print("=" * 50)

    cases = [
        ('["人像", "portrait", "cinematic"]', ["人像", "portrait", "cinematic"]),
        ('当然！以下是标签：\n["风景", "日落"]', ["风景", "日落"]),
        ('```json\n["tag1", "tag2"]\n```', ["tag1", "tag2"]),
        ("这不是JSON", []),
        ("[]", []),
        ('["  ", ""]', []),
        ('["单个标签"]', ["单个标签"]),
    ]

    all_pass = True
    for i, (input_text, expected) in enumerate(cases):
        result = _parse_tag_response(input_text)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  Case {i+1}: {status}")
        if status == "FAIL":
            print(f"    输入: {input_text!r}")
            print(f"    期望: {expected}")
            print(f"    实际: {result}")

    print(f"\n纯函数测试: {'全部通过' if all_pass else '存在失败'}\n")
    return all_pass


# ---------- 网络测试（需要 LM Studio 运行） ----------

async def test_connection(base_url: str):
    """测试 1: 基本连接 - 发送最小请求验证 API 可达。"""
    import aiohttp

    print("=" * 50)
    print(f"测试 2: 连接测试 ({base_url})")
    print("=" * 50)

    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    body = {
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 8,
    }

    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                endpoint, json=body, headers={"Content-Type": "application/json"}
            ) as resp:
                print(f"  HTTP 状态码: {resp.status}")
                if resp.status != 200:
                    text = await resp.text()
                    print(f"  错误响应: {text[:300]}")
                    return False

                data = await resp.json()
                model = data.get("model", "(未知)")
                print(f"  模型: {model}")

                content = ""
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    pass
                safe_content = content[:100].encode("ascii", errors="replace").decode("ascii")
                print(f"  回复内容: {safe_content}")
                print(f"  连接测试: PASS\n")
                return True

    except aiohttp.ClientConnectorError as e:
        print(f"  连接失败: {e}")
        print(f"  请确认 LM Studio 已启动并监听 {base_url}")
        print(f"  连接测试: FAIL\n")
        return False
    except asyncio.TimeoutError:
        print(f"  连接超时（15秒）")
        print(f"  连接测试: FAIL\n")
        return False
    except Exception as e:
        print(f"  未知错误: {type(e).__name__}: {e}")
        print(f"  连接测试: FAIL\n")
        return False


async def test_auto_tag(base_url: str):
    """测试 2: 自动打标签 - 发送提示词并解析标签。"""
    import aiohttp

    print("=" * 50)
    print(f"测试 3: 自动打标签 ({base_url})")
    print("=" * 50)

    system_prompt = (
        "你是一个图像生成提示词分析专家。根据以下正向和负向提示词，生成5到15个相关标签。\n"
        "标签应涵盖：主题、风格、画质、场景、人物特征、光照、构图等维度。\n"
        "标签可以是中文或英文，每个标签2-4个字/单词。\n"
        "只返回 JSON 数组，不要其他文字。\n\n"
        '示例输出: ["人像", "电影感", "黄金时段", "浅景深", "portrait", "cinematic"]'
    )

    user_prompt = (
        "正向提示词:\n"
        "1girl, solo, long hair, looking at viewer, smile, blonde hair, "
        "blue eyes, dress, standing, outdoors, sky, cloud, sunlight, "
        "masterpiece, best quality, cinematic lighting, depth of field\n\n"
        "负向提示词:\n"
        "lowres, bad anatomy, bad hands, text, error, worst quality"
    )

    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 512,
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            print("  发送请求中（可能需要等待模型加载）...")
            async with session.post(
                endpoint, json=body, headers={"Content-Type": "application/json"}
            ) as resp:
                print(f"  HTTP 状态码: {resp.status}")
                if resp.status != 200:
                    text = await resp.text()
                    print(f"  错误响应: {text[:300]}")
                    return False

                data = await resp.json()

        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            print(f"  LLM 返回格式异常: {json.dumps(data, ensure_ascii=False)[:300]}")
            return False

        print(f"  LLM 原始返回: {content}")

        tags = _parse_tag_response(content)
        if not tags:
            print(f"  解析失败: 无法从返回中提取标签数组")
            print(f"  自动打标签: FAIL\n")
            return False

        print(f"  解析出 {len(tags)} 个标签: {tags}")
        print(f"  自动打标签: PASS\n")
        return True

    except aiohttp.ClientConnectorError as e:
        print(f"  连接失败: {e}")
        return False
    except asyncio.TimeoutError:
        print(f"  请求超时（60秒），模型可能正在加载")
        return False
    except Exception as e:
        print(f"  未知错误: {type(e).__name__}: {e}")
        return False


async def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:1234"
    print(f"\nLM Studio 连接测试")
    print(f"目标地址: {base_url}")
    print(f"完整端点: {base_url.rstrip('/')}/v1/chat/completions\n")

    # 测试 1: 纯函数
    parse_ok = test_parse_tag_response()

    # 测试 2: 连接
    conn_ok = await test_connection(base_url)

    # 测试 3: 自动打标签（仅在连接成功时）
    tag_ok = False
    if conn_ok:
        tag_ok = await test_auto_tag(base_url)
    else:
        print("跳过自动打标签测试（连接失败）\n")

    # 汇总
    print("=" * 50)
    print("测试汇总")
    print("=" * 50)
    print(f"  解析函数: {'PASS' if parse_ok else 'FAIL'}")
    print(f"  连接测试: {'PASS' if conn_ok else 'FAIL'}")
    print(f"  自动标签: {'PASS' if tag_ok else 'FAIL' if conn_ok else 'SKIP'}")

    if parse_ok and conn_ok and tag_ok:
        print("\n全部测试通过！LLM 集成可以正常工作。\n")
    elif not conn_ok:
        print("\n连接失败。请检查：")
        print(f"  1. LM Studio 是否已启动")
        print(f"  2. 服务是否监听在 {base_url}")
        print(f"  3. 是否已加载模型")
        print(f"  4. 防火墙/网络是否允许连接\n")


if __name__ == "__main__":
    asyncio.run(main())
