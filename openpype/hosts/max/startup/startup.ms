-- OpenPype Init Script
(
    local sysPath = dotNetClass "System.IO.Path"
	local sysDir = dotNetClass "System.IO.Directory"
	local localScript =  getThisScriptFilename()
    local startup = sysPath.Combine (sysPath.GetDirectoryName localScript) "startup.py"

    python.ExecuteFile startup
)