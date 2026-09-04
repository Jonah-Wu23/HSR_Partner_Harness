export interface MufyFieldMeta {
  key: string;
  label: string;
  description: string;
  /** 已知字符串子键默认按多行文本呈现。 */
  multiline?: boolean;
  /** 首次添加该键时的初始结构（仅结构，不写入任何内容）。 */
  createDefault: () => unknown;
}

export interface MufyBlockMeta {
  key: string;
  title: string;
  description: string;
  /** event_system 子树内的 runtime_trigger 保留字段按契约呈现。 */
  triggerAware?: boolean;
  fields: MufyFieldMeta[];
}

const objectDefault = () => ({});
const textDefault = () => "";

/** 已知子键清单来自 docs/design/research/mufy角色卡参考.md 的模板键名，仅作表单引导。 */
export const MUFY_BLOCKS: MufyBlockMeta[] = [
  {
    key: "world_architecture",
    title: "世界架构",
    description: "世界基底、地理与城市、社会系统、文化与哲学——角色存在的土壤。",
    fields: [
      { key: "world_foundation", label: "世界基底", description: "这个世界是什么：一句话基调、类型与叙事节奏。", createDefault: objectDefault },
      { key: "geography", label: "地理与城市", description: "主舞台、城市分区与关键地点。", createDefault: objectDefault },
      { key: "social_systems", label: "社会系统", description: "阶层、经济、职业生态与法律道德框架。", createDefault: objectDefault },
      { key: "culture_philosophy", label: "文化与哲学", description: "主流价值观、人际规范与日常生活质感。", createDefault: objectDefault },
    ],
  },
  {
    key: "character_architecture",
    title: "角色架构",
    description: "身份锚点、外貌与感官、语言指纹、行为状态机、心理内核、生活方式、背景故事与元指令。",
    fields: [
      { key: "identity", label: "身份锚点", description: "姓名、称呼、年龄与核心矛盾。", createDefault: objectDefault },
      { key: "physical_presence", label: "外貌与感官", description: "第一印象、身体、面部与感官签名。", createDefault: objectDefault },
      { key: "voice_system", label: "语言指纹", description: "语言画像、语气光谱、对象切换与非语言沟通。", createDefault: objectDefault },
      { key: "behavioral_states", label: "行为状态机", description: "默认状态、情绪光谱与特殊状态。", createDefault: objectDefault },
      { key: "psychological_core", label: "心理内核", description: "童年烙印、核心恐惧与需求、防御机制。", createDefault: objectDefault },
      { key: "lifestyle", label: "生活方式", description: "一日时间线、习惯与品味系统。", createDefault: objectDefault },
      { key: "background", label: "背景故事", description: "过去、转折点与现在。", createDefault: objectDefault },
      { key: "meta_instructions", label: "元指令", description: "给模型的导演笔记：绝对准则、禁区与互动引导。", createDefault: objectDefault },
    ],
  },
  {
    key: "relationship_system",
    title: "关系系统",
    description: "关系建立模式、阶段门控、与用户关系设定和重要人物。",
    fields: [
      { key: "bonding_pattern", label: "关系建立模式", description: "从陌生到重要的阶段表现。", createDefault: objectDefault },
      { key: "relationship_gates", label: "关系阶段门控", description: "推进原则、阶段列表、回退机制与不可逆节点。", createDefault: objectDefault },
      { key: "with_user", label: "与用户关系", description: "关系定位、日常互动、冲突与吃醋模式。", createDefault: objectDefault },
      { key: "key_npcs", label: "重要人物关系", description: "对角色有意义的 NPC 及其功能。", createDefault: objectDefault },
    ],
  },
  {
    key: "event_system",
    title: "事件系统",
    description: "开局模式、时间线事件、条件触发器与随机事件池。声明了 runtime_trigger 的条目按回合触发规则呈现。",
    triggerAware: true,
    fields: [
      { key: "opening_scenarios", label: "开局模式", description: "固定开局或多开局池。", createDefault: objectDefault },
      { key: "timeline_events", label: "时间线事件", description: "绝对与相对时间轴上的既定剧情节点。", createDefault: objectDefault },
      { key: "conditional_triggers", label: "条件触发器", description: "按关系、状态、关键词或数值条件触发的事件。", createDefault: objectDefault },
      { key: "random_events", label: "随机事件池", description: "日常、中等、重大与彩蛋事件的抽取池。", createDefault: objectDefault },
    ],
  },
  {
    key: "narrative_rules",
    title: "叙事规则",
    description: "节奏、视角、对话规则、暴力描写与全局禁区。",
    fields: [
      { key: "pacing", label: "节奏控制", description: "整体节奏与各类场景的写法。", createDefault: objectDefault },
      { key: "perspective", label: "视角与叙述", description: "叙述视角与内心描写规则。", createDefault: objectDefault },
      { key: "dialogue_rules", label: "对话规则", description: "对话占比、风格与禁止的对话模式。", createDefault: objectDefault },
      { key: "violence_rules", label: "暴力与冲突描写", description: "暴力场景的描写边界，自由文本。", createDefault: textDefault, multiline: true },
      { key: "absolute_bans", label: "全局禁区", description: "绝对不可违反的描写、行为与词汇禁区。", createDefault: objectDefault },
    ],
  },
];

/** hsr 下由应用其他功能维护的键：这里只读展示，编辑入口在各自功能页。 */
export const MANAGED_KEYS: readonly string[] = ["schema_version", "avatar_asset", "voice_profile"];

export const MANAGED_KEY_NOTES: Record<string, string> = {
  schema_version: "hsr 契约版本，由导入与保存流程维护。",
  avatar_asset: "头像资产引用，由资产服务维护。",
  voice_profile: "角色音色状态，由「角色语音」页维护。",
};
