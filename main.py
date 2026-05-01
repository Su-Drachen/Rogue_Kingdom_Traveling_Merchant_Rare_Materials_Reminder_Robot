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
		self.target_keywords = ["棱镜", "棱彩", "祝福", "炫彩", "国王", "奇异血脉"] #"果", "晶", "玉", "蛋"
		self.beijing_tz = timezone(timedelta(hours=8))

	def get_beijing_now(self):
		return datetime.now(self.beijing_tz)

	def get_current_window_target(self):
		"""
		计算当前时间所属的任务窗口起点 (7:55, 11:55, 15:55, 19:55)
		"""
		now = self.get_beijing_now()
		targets = [
			now.replace(hour=7, minute=55, second=0, microsecond=0),
			now.replace(hour=11, minute=55, second=0, microsecond=0),
			now.replace(hour=15, minute=55, second=0, microsecond=0),
			now.replace(hour=19, minute=55, second=0, microsecond=0)
		]

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
					"content": json.dumps(state, ensure_ascii=False, indent=2)
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
				if data.get("code") != 0: return None, None, False

				res_data = data.get("data", {})
				activities = res_data.get("merchantActivities") or res_data.get("merchant_activities") or []

				if not activities:
					return None, None, False

				props = activities[0].get("get_props", [])
				hit_items = []  # 匹配关键词的
				all_items = []  # 当前时段所有的
				api_refreshed = len(props) > 0

				for item in props:
					name = item.get("name", "")
					start_time = item.get("start_time")
					end_time = item.get("end_time")

					if start_time and end_time:
						# 只记录当前生效的商品
						if not (int(start_time) <= now_ms < int(end_time)):
							continue

						st_dt = datetime.fromtimestamp(int(start_time) / 1000, self.beijing_tz)
						et_dt = datetime.fromtimestamp(int(end_time) / 1000, self.beijing_tz)
						time_str = f"({st_dt.strftime('%H:%M')}-{et_dt.strftime('%H:%M')})"
						item_info = f"{name} {time_str}"

						# 放入全量列表
						all_items.append(item_info)

						# 判断是否命中关键词
						if any(kw in name for kw in self.target_keywords):
							hit_items.append(f"· {item_info}")

				return hit_items, all_items, api_refreshed
			except Exception as e:
				print(f"数据获取异常: {e}")
				return None, None, False

	async def send_webhook(self, hit_list):
		if not hit_list: return
		title = "📢 【洛克王国】稀有物资刷新提醒！\n"
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
		# 只要记录里有商品列表且时间匹配，就认为已处理
		has_product_recorded = "products" in state and state.get("products")

		print(f"当前时间窗口: {target_str}")

		# 3. 判断是否需要执行检测
		if last_time == target_str and has_product_recorded:
			print("该时间段已记录过商品信息，跳过。")
			return

		# 4. 执行 API 检测
		hit_list, all_list, api_refreshed = await self.get_filtered_products()

		if api_refreshed:
			print("API 已刷新商品。")
			if hit_list:
				await self.send_webhook(hit_list)
				print("发现目标物品，已推送。")
			else:
				print("未发现目标物品，仅记录全量清单。")

			# 更新 Gist 状态：保存时间点和当前所有的商品列表
			await self.update_gist_state({
				"last_time": target_str,
				"has_product": True,  # 保留原字段兼容
				"products": all_list if all_list else ["无商品数据"]
			})
		else:
			print("API 尚未返回有效商品信息。")
			# 记录当前窗口，但标记商品为空，下次运行会再次触发
			await self.update_gist_state({
				"last_time": target_str,
				"has_product": False,
				"products": []
			})


if __name__ == "__main__":
	bot = RocomTargetBot()
	asyncio.run(bot.run())
