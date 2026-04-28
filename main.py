import httpx
import asyncio
import time
import os
from datetime import datetime, timedelta, timezone


class RocomTargetBot:
	def __init__(self):
		self.api_key = os.getenv("MY_API_KEY")
		self.webhook_url = os.getenv("MY_WEBHOOK")
		self.api_base_url = "https://wegame.shallow.ink"
		self.target_keywords = ["棱镜", "棱彩", "祝福", "炫彩", "国王", "血脉秘药"]

		# 【新增】定义北京时区 UTC+8
		self.beijing_tz = timezone(timedelta(hours=8))

	def get_beijing_now(self):
		"""获取北京时间的 datetime 对象"""
		return datetime.now(self.beijing_tz)

	async def get_filtered_products(self):
		path = "/api/v1/games/rocom/merchant/info"

		# Unix 时间戳是全球统一的，不需要加 8 小时，它直接代表“当前这一刻”
		now_ms = time.time() * 1000

		headers = {"X-API-Key": self.api_key}

		async with httpx.AsyncClient(timeout=15.0) as client:
			try:
				resp = await client.get(f"{self.api_base_url}{path}", headers=headers)
				data = resp.json()
				if data.get("code") != 0: return None

				res_data = data.get("data", {})
				activities = res_data.get("merchantActivities") or res_data.get("merchant_activities") or []
				if not activities: return None

				props = activities[0].get("get_props", [])
				hit_items = []

				for item in props:
					name = item.get("name", "")
					start_time = item.get("start_time")
					end_time = item.get("end_time")

					if start_time and end_time:
						if not (int(start_time) <= now_ms < int(end_time)):
							continue

					if any(kw in name for kw in self.target_keywords):
						# 【优化】转换显示时间为北京时间
						st_dt = datetime.fromtimestamp(int(start_time) / 1000, self.beijing_tz)
						et_dt = datetime.fromtimestamp(int(end_time) / 1000, self.beijing_tz)

						st_str = st_dt.strftime("%H:%M")
						et_str = et_dt.strftime("%H:%M")
						hit_items.append(f"· {name} ({st_str}-{et_str})")

				return hit_items
			except Exception as e:
				print(f"数据获取异常: {e}")
				return None

	async def send_webhook(self, hit_list):
		title = "📢 【洛克王国】物资刷新提醒！\n"
		body = "\n".join(hit_list)

		# 【优化】推送里的检测时间也要用北京时间
		now_str = self.get_beijing_now().strftime('%Y-%m-%d %H:%M:%S')
		footer = f"\n\n⏰ 检测时间：{now_str}"

		payload = {
			"msgtype": "text",
			"text": {
				"content": f"{title}---------------------------\n{body}{footer}",
				"mentioned_list": ["@all"]
			}
		}

		async with httpx.AsyncClient() as client:
			await client.post(self.webhook_url, json=payload)

	async def run(self):
		hit_list = await self.get_filtered_products()
		if hit_list:
			await self.send_webhook(hit_list)
		else:
			print(f"[{self.get_beijing_now()}] 未发现目标物品。")


if __name__ == "__main__":
	bot = RocomTargetBot()
	asyncio.run(bot.run())
