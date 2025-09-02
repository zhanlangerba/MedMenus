# 启动redis

cd D:\Redis-7.0.8-Windows-x64-msys2
redis-server redis.conf --requirepass snowball2019


user_id: "abc123"
  └── project_id: "proj-001" 
      └── thread_id: "thread-001" (= session_id)
          ├── message_id: "msg-001" (用户输入)
          ├── message_id: "msg-002" (AI回复)
          └── invocation_id: "inv-001" (整个对话轮次)
              
agent_id: "agent-001" (配置哪个AI助手)
instance_id: "inst-001" (哪个后端服务器在处理)


后台启动：dramatiq run_agent_background