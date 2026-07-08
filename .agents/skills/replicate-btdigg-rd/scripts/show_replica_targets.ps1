$targets = @(
    [pscustomobject]@{ Name = "Principal raiz"; Path = "Z:\buscador-rd"; Service = "btdigg-rd"; Port = 9007; Scope = "normal" },
    [pscustomobject]@{ Name = "Replica 2 externa"; Path = "Z:\web\BTDigg + RD 2"; Service = "btdigg-rd-2"; Port = 9027; Scope = "solo con permiso" },
    [pscustomobject]@{ Name = "Replica 3 externa"; Path = "Z:\web\BTDigg + RD 3"; Service = "btdigg-rd-3"; Port = 9037; Scope = "solo con permiso" }
)

$targets | Format-Table -AutoSize
