import json, sys, urllib.request, time
envf, nb, tid = sys.argv[1], sys.argv[2], int(sys.argv[3])
env = {}
for l in open(envf):
    l = l.strip()
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env[k] = v.strip().strip("'\"")
H = {"Authorization": "Bearer " + env["NEWAPI_MANAGEMENT_ACCESS_TOKEN"], "New-Api-User": str(env["NEWAPI_MANAGEMENT_USER_ID"]), "Content-Type": "application/json"}
r = urllib.request.Request(nb + f"/api/token/{tid}", headers=H, method="DELETE")
print("删除令牌", tid, json.loads(urllib.request.urlopen(r, timeout=30).read()).get("success"))
