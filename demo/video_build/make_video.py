from PIL import Image, ImageDraw, ImageFont
import os
OUT="/home/hatch/workspace/BedrockOps/demo/video_build/slides"
os.makedirs(OUT, exist_ok=True)
W,H=1920,1080
BG=(13,17,23); PANEL=(22,27,34); ACC=(88,166,255); GREEN=(63,185,80); YELLOW=(210,153,34); RED=(248,81,73); TEXT=(230,237,243); DIM=(139,148,158)
def font(sz, mono=False, bold=False):
    if mono:
        p="/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    else:
        p="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(p, sz)
def wrap(draw, text, f, maxw):
    lines=[]
    for para in text.split("\n"):
        if not para:
            lines.append(""); continue
        words=para.split(); cur=""
        for w_ in words:
            t=(cur+" "+w_).strip()
            if draw.textlength(t, font=f) <= maxw:
                cur=t
            else:
                lines.append(cur); cur=w_
        lines.append(cur)
    return lines
def slide(idx, title, body, accent=ACC, title_sz=64, body_sz=36, mono_body=True):
    img=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(img)
    d.rectangle([0,0,W,10], fill=accent)
    d.text((90,70), "BedrockOps  •  Amazon Developer Hackathon  •  Alexa+ / MCP", font=font(28), fill=DIM)
    # title wrapped
    tf=font(title_sz, bold=True)
    y=130
    for line in wrap(d, title, tf, W-180):
        d.text((90,y), line, font=tf, fill=TEXT); y+=title_sz+14
    y+=20
    d.rectangle([90,y,W-90,y+2], fill=accent); y+=35
    bf=font(body_sz, mono=mono_body)
    lh=int(body_sz*1.45)
    for line in wrap(d, body, bf, W-220):
        col=TEXT
        low=line.lower()
        if "requires_approval" in low or "stops" in low: col=RED
        elif "healthy" in low or "ok" in low or "2025-11-25" in low or "verified" in low: col=GREEN
        elif "stub" in low or "live\": false" in low or "live: false" in low or "persisted\": false" in low: col=YELLOW
        d.text((110,y), line, font=bf, fill=col); y+=lh
        if y>H-90: break
    d.text((90,H-55), f"{idx}  •  Offline run — every output labels stub / memory / live:false honestly  •  github.com/RwTraylor/BedrockOps", font=font(24), fill=DIM)
    p=f"{OUT}/slide{idx}.png"; img.save(p); print(p)

slide(1,"BedrockOps\nGated, audited cloud operations","Turns a plain-language ops request into an audited,\ngated AWS action — through a real MCP server.\n\nWatch it answer.",ACC,76,42,False)
slide(2,"The problem","Manual CLI troubleshooting is error-prone.\nAd-hoc scripts leave no audit trail.\n\nBedrockOps separates reasoning from execution:\n  • human gates for destructive / costly actions\n  • SHA-256 audit ledger for every operation\n  • results that say live true/false — never bluff",YELLOW,64,38)
slide(3,"First: the tests","$ python -m unittest tests/test_mcp.py\n\nRan 13 tests  •  OK  •  exit code 0\n\nIncluding:\n  • JSON-RPC initialize negotiating 2025-11-25\n  • tools/list + tools/call for all three tools\n  • the approval gate, DynamoDB fake-client path,\n    and the live-probe failure path (never faked)",GREEN,64,36)
slide(4,"Step 1–2: MCP initialize + tools","=== STEP 1: MCP initialize (Streamable HTTP) ===\nprotocol negotiated: 2025-11-25\nserver: BedrockOps 1.0.0\n\n=== STEP 2: tools/list ===\n- system_probe\n- audit_ledger\n- bedrock_route",ACC,58,38)
slide(5,"Step 3: system_probe","=== STEP 3: system_probe dynamodb ===\n{\n  \"status\": \"HEALTHY\",\n  \"service\": \"dynamodb\",\n  \"mode\": \"stub\",\n  \"latency_ms\": 14.2\n}\n\nStub telemetry — labeled in the output itself.",GREEN,58,38)
slide(6,"Step 4: the human gate  ★","Prompt: \"delete the production database\"\n\n=== bedrock_route ===\n{\n  \"live\": false,\n  \"action\": \"requires_approval\",\n  \"reason\": \"gated action keyword\"\n}\n\nIt stops. A destructive request never reaches\nAWS without a human saying yes.",RED,58,38)
slide(7,"Step 5: Bedrock routing","Prompt: \"audit last night's deployment\"\n\n{\n  \"live\": false,\n  \"fallback_reason\": \"NoCredentialsError\",\n  \"action\": \"audit_ledger\"\n}\n\nWith credentials this is a live Amazon Bedrock call.\nHere it honestly says live: false.",YELLOW,58,38)
slide(8,"Step 6: SHA-256 audit ledger","=== audit_ledger ===\n{\n  \"verified\": true,\n  \"sha256\": \"62d5ef9bac352deb...\",\n  \"persisted\": false,\n  \"store\": \"memory\"\n}\n\nDynamoDB when configured — and it says so.",GREEN,58,38)
slide(9,"Open source. MIT. Public.","Official MCP Python SDK (mcp 2.3.0)\nStreamable HTTP at /mcp  •  spec 2025-11-25\nTerraform IaC  •  least-privilege IAM\n\nPublic repo:\ngithub.com/RwTraylor/BedrockOps\n\nNext: the same run, live on AWS.\nBedrockOps — gated, audited, honest.",ACC,64,38)
