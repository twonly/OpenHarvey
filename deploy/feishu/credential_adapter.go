// Built inside the pinned official CLI module; stdout is a private parent pipe.
package main

import (
 "encoding/json"
 "fmt"
 "io"
 "net/http"
 "os"
 "time"
 auth "github.com/larksuite/cli/internal/auth"
 "github.com/larksuite/cli/internal/core"
 "github.com/larksuite/cli/internal/keychain"
)

func main() {
 if len(os.Args)!=3 { fail() }
 cfg,err:=core.RequireConfig(keychain.Default()); if err!=nil { fail() }
 // The caller supplies the expected identity, never select another saved user.
 if cfg.AppID!=os.Args[1] || cfg.UserOpenId!=os.Args[2] || cfg.UserOpenId=="" { fail() }
 token,err:=auth.GetValidAccessToken(&http.Client{Timeout:25*time.Second},auth.NewUATCallOptions(cfg,io.Discard))
 if err!=nil { fail() }
 stored:=auth.GetStoredToken(cfg.AppID,cfg.UserOpenId); if stored==nil { fail() }
 if json.NewEncoder(os.Stdout).Encode(map[string]interface{}{
  "app_id":cfg.AppID,"open_id":cfg.UserOpenId,"access_token":token,
  "expires_at":stored.ExpiresAt/1000,"scope":stored.Scope,
 })!=nil { fail() }
}
func fail(){ fmt.Fprintln(os.Stderr,"Feishu credentials unavailable; reconnect the account");os.Exit(1) }
