import urllib.request
import urllib.error
import ssl

url = "https://api.github.com/repos/Dinesh0401/jobseeker/actions/jobs/101278550732/logs"
req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})

# Create an unverified context to avoid SSL issues locally
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

try:
    with urllib.request.urlopen(req, context=ctx) as response:
        logs = response.read().decode('utf-8')
        print(logs[-2000:])  # Print the last 2000 characters
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code} - {e.reason}")
    print(e.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
