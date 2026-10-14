import json, sys, time, urllib.request
envf, nb, group = sys.argv[1], sys.argv[2], sys.argv[3]
env = {}
for l in open(envf):
    l = l.strip()
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env[k] = v.strip().strip("'\"")
H = {"Authorization": "Bearer " + env["NEWAPI_MANAGEMENT_ACCESS_TOKEN"], "New-Api-User": str(env["NEWAPI_MANAGEMENT_USER_ID"]), "Content-Type": "application/json"}
def call(m, p, b=None):
    r = urllib.request.Request(nb + p, data=(json.dumps(b).encode() if b is not None else None), headers=H, method=m); return json.loads(urllib.request.urlopen(r, timeout=60).read())
name = f"realclient-{int(time.time())}"
call("POST", "/api/token/", {"name": name, "expired_time": int(time.time()) + 3600, "unlimited_quota": True, "model_limits_enabled": False, "group": group})
tid = next(int(i["id"]) for i in call("GET", "/api/token/?p=0&page_size=100")["data"]["items"] if i["name"] == name)
print(tid, "sk-" + call("POST", f"/api/token/{tid}/key")["data"]["key"])
