import httpx
import asyncio
import time
import os
import json
from datetime import datetime, timedelta, timezone


class RocomTargetBot:
	def __init__(self):
		self.api_key = os.getenv("MY_API_KEY")
		self.webhook_url = os.getenv("MY_WEBHOOK")
		self.gist_id = os.getenv("GIST_ID")
		self.gist_token = os.getenv("GIST_TOKEN")

		self.api_base_url = "https://wegame.shallow.ink"
		self.target_keywords = ["棱镜", "棱彩", "祝福", "炫彩", "国王", "奇异血脉",  "果","晶","玉","蛋"]
		self.beijing_tz = timezone(timedelta(hours=8))


	def get_beijing_now(self):
		return datetime.now(self.beijing_tz)

	def get_current_window_target(self):
		"""
		计算当前时间所属的任务窗口起点 (7:55, 11:55, 15:55, 19:55)
		例如：8:05 执行，对应的窗口是 7:55；12:05 执行，对应 11:55
		"""
		now = self.get_beijing_now()
		# now = "12:49"
		print(now)
		# 定义四个标准触发点
		targets = [
			now.replace(hour=7, minute=55, second=0, microsecond=0),
			now.replace(hour=11, minute=55, second=0, microsecond=0),
			now.replace(hour=15, minute=55, second=0, microsecond=0),
			now.replace(hour=19, minute=55, second=0, microsecond=0)
		]

		# 寻找当前时间之前（或相等）的最后一个 target
		# 如果当前时间比 7:55 还早，则取前一天最后的 19:55
		past_targets = [t for t in targets if t <= now]
		if not past_targets:
			yesterday = now - timedelta(days=1)
			return yesterday.replace(hour=19, minute=55, second=0, microsecond=0)

		return max(past_targets)

	async def get_gist_state(self):
		"""从 Gist 读取状态"""
		url = f"https://api.github.com/gists/{self.gist_id}"
		headers = {"Authorization": f"token {self.gist_token}"}
		async with httpx.AsyncClient() as client:
			try:
				resp = await client.get(url, headers=headers)
				if resp.status_code == 200:
					files = resp.json().get("files", {})
					content = files.get("rocom_state.json", {}).get("content", "{}")
					return json.loads(content)
			except Exception as e:
				print(f"读取 Gist 异常: {e}")
			return {}

	async def update_gist_state(self, state):
		"""更新状态到 Gist"""
		url = f"https://api.github.com/gists/{self.gist_id}"
		headers = {
			"Authorization": f"token {self.gist_token}",
			"Accept": "application/vnd.github.v3+json"
		}
		payload = {
			"files": {
				"rocom_state.json": {
					"content": json.dumps(state)
				}
			}
		}
		async with httpx.AsyncClient() as client:
			try:
				await client.patch(url, headers=headers, json=payload)
			except Exception as e:
				print(f"更新 Gist 异常: {e}")

	async def get_filtered_products(self):
		path = "/api/v1/games/rocom/merchant/info"
		now_ms = time.time() * 1000
		headers = {"X-API-Key": self.api_key}

		async with httpx.AsyncClient(timeout=15.0) as client:
			try:
				resp = await client.get(f"{self.api_base_url}{path}", headers=headers)
				data = resp.json()
				if data.get("code") != 0: return None, False

				res_data = data.get("data", {})
				activities = res_data.get("merchantActivities") or res_data.get("merchant_activities") or []

				# 如果 activities 为空，说明商品还没刷新出来
				if not activities:
					return None, False

				props = activities[0].get("get_props", [])
				hit_items = []
				# 只要 activities 有内容，我们就认为 API 已经刷新了
				api_refreshed = len(props) > 0

				for item in props:
					name = item.get("name", "")
					start_time = item.get("start_time")
					end_time = item.get("end_time")

					if start_time and end_time:
						if not (int(start_time) <= now_ms < int(end_time)):
							continue

					if any(kw in name for kw in self.target_keywords):
						st_dt = datetime.fromtimestamp(int(start_time) / 1000, self.beijing_tz)
						et_dt = datetime.fromtimestamp(int(end_time) / 1000, self.beijing_tz)
						hit_items.append(f"· {name} ({st_dt.strftime('%H:%M')}-{et_dt.strftime('%H:%M')})")

				return hit_items, api_refreshed
			except Exception as e:
				print(f"数据获取异常: {e}")
				return None, False

	async def send_webhook(self, hit_list):
		if not hit_list: return
		title = "📢 【洛克王国】物资刷新提醒！（测试版修改关注列表）\n"
		body = "\n".join(hit_list)
		now_str = self.get_beijing_now().strftime('%Y-%m-%d %H:%M:%S')
		footer = f"\n\n⏰ 检测时间：{now_str}"
		payload = {
			"msgtype": "text",
			"text": {
				"content": f"{title}---------------------------\n{body}{footer}",
				"mentioned_list": [""]
			}
		}
		async with httpx.AsyncClient() as client:
			await client.post(self.webhook_url, json=payload)

	async def run(self):
		# 1. 确定当前应该对应的窗口时间
		target_dt = self.get_current_window_target()
		target_str = target_dt.strftime("%Y-%m-%d %H:%M")

		# 2. 读取 Gist 状态
		state = await self.get_gist_state()
		last_time = state.get("last_time")
		has_product = state.get("has_product", False)

		print(f"当前时间窗口: {target_str}")
		print(f"Gist 记录: 时间={last_time}, 是否有商品={has_product}")

		# 3. 判断是否需要执行检测
		# 条件：如果 Gist 时间匹配 且 has_product 为 True，则跳过
		if last_time == target_str and has_product:
			print("该时间段已成功执行并发现/处理过商品，跳过。")
			return

		# 4. 执行 API 检测
		hit_list, api_refreshed = await self.get_filtered_products()

		if api_refreshed:
			# 只要 API 刷新了（不管有没有关键词命中的），我们就更新 Gist 标记该时段已处理
			print("API 已刷新商品。")
			if hit_list:
				await self.send_webhook(hit_list)
				print("发现目标物品，已推送。")
			else:
				print("未发现目标物品，仅记录状态。")

			# 更新 Gist 状态为：当前时间点，且已成功获取商品
			await self.update_gist_state({
				"last_time": target_str,
				"has_product": True
			})
		else:
			# API 还没刷新（没数据）
			print("API 尚未返回有效商品信息。")
			# 记录当前窗口，但标记无商品，下次运行会再次触发
			await self.update_gist_state({
				"last_time": target_str,
				"has_product": False
			})


if __name__ == "__main__":
	bot = RocomTargetBot()
	asyncio.run(bot.run())
