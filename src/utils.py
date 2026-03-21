import time

import time

# 计时器装饰器
def measure_time(message=""):
    """
    计时器装饰器，用于测量函数的执行时间，并输出自定义信息
    :param message: 用户自定义的备注信息
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()  # 记录开始时间
            result = func(*args, **kwargs)
            end_time = time.time()  # 记录结束时间
            print(f"{message} Function '{func.__name__}' took {end_time - start_time:.2f} seconds to execute.")
            return result
        return wrapper
    return decorator

