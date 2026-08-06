from langgraph.store.base import BaseStore
from . import State
from utils.models import create_deepseek_model
from pydantic import BaseModel, Field
from typing import List
from langchain_core.messages import ToolMessage, SystemMessage, HumanMessage
import time


def load_memory(state: State, store: BaseStore):
    user_id = str(state.get("userId", 0))
    namespace = ('memory', user_id)
    existing_memory = store.get(namespace, "user_memory")
    preference = []
    if existing_memory and existing_memory.value:
        data = existing_memory.value
        profile = data.get('preference') if isinstance(data, dict) else data
        preference = profile.get('legal_preference', []) if isinstance(profile, dict) else getattr(profile, 'legal_preference', [])
    return {"preference": preference}


class OutPut(BaseModel):
    user_id: str = Field(
        default="",
        description="用户的Id"
    )
    legal_preference:List[str] = Field(
        default_factory=lambda: ["通用民事"],
        description="用户关注的法律领域列表，按关注度从高到低排序，最多5个"
    )
    
create_memory_prompt="""
你是一个法律用户画像分析器。

你的唯一任务是：根据用户对话，更新其关注的**法律领域列表**。
输出必须是 JSON，且 legal_preference 永远是一个字符串数组。

# 可选法律领域（仅限以下枚举）
合同纠纷、劳动争议、婚姻家庭、知识产权、公司治理、
刑事辩护、房产土地、侵权责任、金融证券、通用民事

# 更新规则
1. 优先依据用户最新发言判断。
2. 如果用户明确提及某领域（如“劳动合同”“离婚”“专利”），将该领域**插入数组首位**。
3. 如果用户问题描述符合某领域常识（如“被辞退赔偿”“彩礼返还”），同样将其置顶。
4. 如果用户同时涉及多个领域，选择**最核心、最紧急**的一个置顶，其余保留。
5. 如果用户问题不涉及法律或无法判断，数组仅保留["通用民事"]。
6. 如果用户只是打招呼、感谢、无关闲聊，**原样返回现有数组，不做任何修改**。
7. 数组按“关注度从高到低”排序。
8. 数组长度不超过 5 个，超出时丢弃最末位的旧领域。

# 当前已知用户偏好
{existing_domain}

# 最近对话
{conversation}

# 输出格式（必须遵守）
{{
  "legal_preference": ["领域1", "领域2", ...]
}}

# 示例
当前偏好：["合同纠纷"]
用户输入：公司拖欠工资怎么办
输出：
{{"legal_preference": ["劳动争议", "合同纠纷"]}}

当前偏好：["劳动争议"]
用户输入：谢谢，明白了
输出：
{{"legal_preference": ["劳动争议"]}}

当前偏好：["劳动争议"]
用户输入：房子拆迁怎么补偿
输出：
{{"legal_preference": ["房产土地", "劳动争议"]}}

当前偏好：["通用民事"]
用户输入：今天天气不错
输出：
{{"legal_preference": ["通用民事"]}}
"""

model = create_deepseek_model(temperature=0.1).with_structured_output(OutPut)
def create_memory(state:State,store:BaseStore):
    print("记忆创建中")
    user_id = str(state.get("userId", 0))
    namespace = ("memory", user_id)
    formatted_memory = state["preference"]
    conversation_text = "\n".join(
        f"{'用户' if isinstance(m, HumanMessage) else 'AI'}: {m.content[:500] if isinstance(m.content, str) else str(m.content)[:500]}"
        for m in state.get("messages", [])[-4:]
    )
    formatted_system_message = SystemMessage(content=create_memory_prompt.format(conversation=conversation_text, existing_domain=formatted_memory))

    user_prompt = HumanMessage(content="Please analyze the conversation and update the customer's memory profile according to the instructions.")
    for attempt in range(3):
        try:
            updated_memory = model.invoke([formatted_system_message, user_prompt])
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            return  # 记忆更新失败，静默跳过
    key = 'user_memory'
    store.put(namespace, key, {"preference": updated_memory})