# 架构设计

## 1. 整体架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                    iOS App (SwiftUI)                           │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   │
│  │ 截图选择  │ → │ OCR处理  │ → │ 文本拼接 │ → │ HTTP请求 │   │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │ REST API (JSON)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Python 服务端 (FastAPI + DeepAgents)               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              DeepAgents 智能体 (create_deep_agent)        │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │  │
│  │  │  规划工具    │  │ 文件系统    │  │  子智能体       │  │  │
│  │  │  (TODO)     │  │ (上下文管理) │  │  (Subagents)   │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │  │
│  │                           │                               │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │              自定义工具 (Tools)                     │  │  │
│  │  │  • create_meeting  • create_contact  • update_contact│  │  │
│  │  │  • query_contacts  • generate_insight               │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              数据层                                        │  │
│  │  • PostgreSQL (联系人数据 + 会话状态)                     │  │
│  │  • LangGraph 状态持久化 (checkpointer)                   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

核心设计理念：
- iOS 端：只负责图片采集、OCR 文字提取和结果展示，所有智能逻辑由服务端处理。
- 服务端：基于 DeepAgents 构建“Lite Ailoha 智能体”，内置规划、文件系统和子智能体能力
- 状态持久化：利用 LangGraph 的 checkpointer 机制，支持多轮对话和任务延续

疑惑：OCR 处理放在 iOS 客户端还是服务端？iOS 客户端是否可行？


## 2.项目目录结构

```
lite-ailoha/
├── .env.example                      # 环境变量模板（服务端用）
├── .gitignore                        # Git 忽略规则（同时覆盖 iOS 和 Python）
├── README.md                         # 项目总览、架构图、快速启动指南
├── docker-compose.yml                # 一键编排：服务端 + PostgreSQL + (可选) Redis
├── docs/                             # 项目文档
│   ├── ARCHITECTURE.md               # 详细架构设计说明
│   ├── API_REFERENCE.md              # 后端 REST API 接口文档
│   ├── PRD.md                        # 产品需求文档，详细描述功能、界面、技术选型
│
├── ios/                              # 📱 iOS 客户端 (Xcode Project)
│   ├── LiteAilohaApp.xcodeproj/         # Xcode 工程文件
│   ├── LiteAilohaApp/                   # 主源码目录
│   │   ├── App/
│   │   │   └── LiteAilohaApp.swift   # App 入口，依赖注入配置
│   │   │
│   │   ├── Models/                   # 数据模型层（纯 Swift 结构体）
│   │   │   ├── Action.swift          # 动作枚举 (含关联值)
│   │   │   ├── AnalysisRequest.swift # 网络请求体
│   │   │   ├── AnalysisResponse.swift# 网络响应体
│   │   │   └── Insight.swift         # 洞察模型
│   │   │
│   │   ├── Views/                    # 视图层（SwiftUI）
│   │   │   ├── Main/
│   │   │   │   ├── MainView.swift    # 主容器（状态驱动，核心逻辑绑定）
│   │   │   │   └── Components/
│   │   │   │       ├── PhotoPickerView.swift    # 图片选择器
│   │   │   │       ├── OCRTextView.swift        # OCR 文字展示/编辑区
│   │   │   │       └── SupplementTextView.swift # 补充文字输入框
│   │   │   ├── Cards/
│   │   │   │   ├── ActionCardListView.swift # 卡片列表容器
│   │   │   │   ├── ActionCardRow.swift      # 单张卡片（含展开动画）
│   │   │   │   └── ActionCardDetailSheet.swift # (可选) 卡片编辑详情弹窗
│   │   │   └── Results/
│   │   │       ├── ExecutionResultView.swift # 执行完成结果页
│   │   │       └── InsightBannerView.swift   # AI 洞察横幅
│   │   │
│   │   ├── ViewModels/               # 视图模型层（状态管理）
│   │   │   └── MainViewModel.swift   # 主状态机（@Observable 宏）
│   │   │
│   │   ├── Services/                 # 服务层（网络、系统能力）
│   │   │   ├── APIService.swift      # 封装后端 HTTP 请求
│   │   │   ├── OCRService.swift      # 封装 Apple Vision OCR
│   │   │   └── PermissionService.swift # 统一管理相册/日历/通讯录权限
│   │   │
│   │   ├── Extensions/               # 全局扩展
│   │   │   ├── View+Extensions.swift # 通用 UI 修饰符（Loading、Error）
│   │   │   ├── UIImage+Extensions.swift # 图片方向修正/压缩
│   │   │   └── UserDefaults+Extensions.swift # AppStorage 缓存封装
│   │   │
│   │   ├── Resources/                # 资源文件
│   │   │   ├── Config.plist          # 服务端地址（BaseURL）外部配置
│   │   │   ├── Info.plist            # iOS 系统配置（权限声明）
│   │   │   └── Assets.xcassets       # 图标、配色、启动图
│   │   │
│   │   └── Supporting Files/
│   │       └── LiteAiloha.entitlements # 沙盒/推送权限（按需）
│   │
│   └── LiteAilohaTests/              # 单元测试目标
│       ├── ViewModels/
│       │   └── MainViewModelTests.swift
│       └── Services/
│           └── OCRServiceTests.swift
│
├── server/                           # Python 后端 (FastAPI + DeepAgents)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI 应用实例、路由注册
│   │   │
│   │   ├── api/                      # 路由层（接口定义）
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── endpoints/
│   │   │   │   │   ├── analyze.py   # POST /api/v1/analyze 核心接口
│   │   │   │   │   └── health.py    # GET /health 健康检查
│   │   │   │   └── router.py        # 统一注册 v1 路由
│   │   │
│   │   ├── core/                     # 核心配置与基础设施
│   │   │   ├── __init__.py
│   │   │   ├── config.py             # 读取 .env 环境变量 (pydantic-settings)
│   │   │   ├── database.py           # SQLAlchemy 引擎 + SessionLocal 依赖注入
│   │   │   └── logging.py            # 日志配置（便于生产调试）
│   │   │
│   │   ├── models/                   # 数据模型层
│   │   │   ├── __init__.py
│   │   │   ├── sqlalchemy/           # ORM 实体（数据库表）
│   │   │   │   ├── base.py           # 基类（id, created_at, updated_at）
│   │   │   │   └── contact.py        # 联系人表（含 meeting_count 等字段）
│   │   │   └── schemas/              # Pydantic 模型（API 请求/响应契约）
│   │   │       ├── request.py        # AnalyzeRequest
│   │   │       ├── response.py       # AnalyzeResponse, ActionCard
│   │   │       └── action.py         # 各类动作的细化 Schema
│   │   │
│   │   ├── agent/                    # 🤖 DeepAgents 核心逻辑（面试亮点）
│   │   │   ├── __init__.py
│   │   │   ├── deep_agent.py         # create_deep_agent 工厂函数
│   │   │   ├── prompts.py            # System Prompt（精心调优的指令）
│   │   │   ├── tools.py              # 自定义工具函数集
│   │   │   │   (create_meeting, create_contact, update_contact,
│   │   │   │    query_contacts, generate_insight)
│   │   │   └── callbacks.py          # (可选) 自定义回调，便于流式输出或日志
│   │   │
│   │   ├── services/                 # 业务服务层（解耦工具实现）
│   │   │   ├── __init__.py
│   │   │   ├── calendar_service.py   # 实际调用日历 API 逻辑（可 Mock）
│   │   │   ├── contact_service.py    # 实际 CRUD 通讯录逻辑
│   │   │   └── insight_service.py    # 关联规则引擎（离线生成洞察备选）
│   │   │
│   │   └── utils/                    # 工具辅助函数
│   │       ├── __init__.py
│   │       └── json_encoder.py       # 自定义 JSON 序列化（处理 datetime）
│   │
│   ├── migrations/                   # Alembic 数据库迁移脚本
│   │   ├── env.py
│   │   ├── versions/
│   │   │   └── 20260607_initial_create_contacts.py
│   │   └── alembic.ini
│   │
│   ├── tests/                        # 单元测试与集成测试
│   │   ├── __init__.py
│   │   ├── conftest.py               # pytest 夹具（测试数据库、客户端）
│   │   ├── test_api/
│   │   │   └── test_analyze.py       # 测试分析接口
│   │   └── test_agent/
│   │       └── test_tools.py         # 测试自定义工具函数
│   │
│   ├── .env                          # (实际文件，gitignore) 存放 OPENAI_API_KEY 等
│   ├── requirements.txt              # 生产环境依赖列表
│   └── requirements-dev.txt          # 开发环境依赖（pytest, black, ruff）
```

Server 端使用 DeepAgents 的持久化存储，如果暂时不想上数据库，是否有别的处理方式？

