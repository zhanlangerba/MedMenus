from dotenv import load_dotenv
load_dotenv(override=True)
from e2b_code_interpreter import Sandbox


sbx = Sandbox()
execution = sbx.run_code("print('hello world')")
print(execution.logs)

files = sbx.files.list("/")
print(files)

# 不再使用时，关闭沙箱
sbx.kill()