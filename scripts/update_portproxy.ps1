# 古い設定を削除
netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0

# WSLのIPを取得
 = wsl hostname -I | ForEach-Object { /bin/bash.Split(" ")[0] }

# 新しい設定を追加
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8000 connectaddress= connectport=8000
