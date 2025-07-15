package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"syscall"
	"time"
)

// CreateNewConsole Windows-specific imports
var (
	CreateNewConsole uint32 = 0x00000010
)

type Request struct {
	Command  string `json:"command"`
	Type     string `json:"type,omitempty"`     // "cmd", "powershell", "wsl"
	Headless bool   `json:"headless,omitempty"` // true for headless, false for headed
	Verbose  bool   `json:"verbose,omitempty"`  // toggleable verbose logging
}

type Response struct {
	Output   string `json:"output"`
	Error    string `json:"error,omitempty"`
	Duration int64  `json:"duration_ms"`
	Debug    string `json:"debug,omitempty"` // verbose logging output
}

func main() {
	scanner := bufio.NewScanner(os.Stdin)

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}

		var req Request
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			// If not JSON, treat as plain command with default settings
			req.Command = line
			req.Type = "cmd"
			req.Headless = true // default to headless for backwards compatibility
		}

		resp := executeCommand(req)

		output, _ := json.Marshal(resp)
		fmt.Println(string(output))
	}
}

func executeCommand(req Request) Response {
	start := time.Now()

	var debugInfo strings.Builder

	if req.Verbose {
		debugInfo.WriteString(fmt.Sprintf("Executing command: %s\n", req.Command))
		debugInfo.WriteString(fmt.Sprintf("Type: %s, Headless: %t\n", req.Type, req.Headless))
	}

	var cmd *exec.Cmd

	switch req.Type {
	case "powershell", "ps":
		cmd = exec.Command("powershell", "-Command", req.Command)
	case "wsl":
		cmd = exec.Command("wsl", "--", "bash", "-c", req.Command)
	default: // "cmd" or empty
		cmd = exec.Command("cmd", "/C", req.Command)
	}

	// Configure window visibility based on a headless flag
	if req.Headless {
		// Hide window for headless execution
		cmd.SysProcAttr = &syscall.SysProcAttr{
			HideWindow: true,
		}
		if req.Verbose {
			debugInfo.WriteString("Running in headless mode (window hidden)\n")
		}
	} else {
		// Create new visible window for headed execution
		if runtime.GOOS == "windows" {
			switch req.Type {
			case "powershell", "ps":
				// Launch PowerShell in a new window
				cmd = exec.Command("powershell", "-NoExit", "-Command", req.Command)
			case "wsl":
				// Launch WSL in a new window using cmd start
				cmd = exec.Command("cmd", "/C", "start", "wsl", "--", "bash", "-c", req.Command+"; read -p 'Press Enter to close...'")
			default: // "cmd" or empty
				// Launch cmd in a new window
				cmd = exec.Command("cmd", "/C", "start", "cmd", "/K", req.Command)
			}

			cmd.SysProcAttr = &syscall.SysProcAttr{
				HideWindow:    false,
				CreationFlags: CreateNewConsole,
			}
		} else {
			// Non-Windows fallback (Linux/Mac)
			switch req.Type {
			case "powershell", "ps":
				cmd = exec.Command("pwsh", "-Command", req.Command) // PowerShell Core
			default:
				cmd = exec.Command("bash", "-c", req.Command)
			}
			cmd.SysProcAttr = &syscall.SysProcAttr{}
		}

		if req.Verbose {
			debugInfo.WriteString("Running in headed mode (new window created)\n")
		}
	}

	if req.Verbose {
		debugInfo.WriteString(fmt.Sprintf("Command args: %v\n", cmd.Args))
	}

	output, err := cmd.CombinedOutput()
	duration := time.Since(start).Milliseconds()

	resp := Response{
		Output:   strings.TrimSpace(string(output)),
		Duration: duration,
	}

	if err != nil {
		resp.Error = err.Error()
		if req.Verbose {
			debugInfo.WriteString(fmt.Sprintf("Command failed with error: %s\n", err.Error()))
		}
	}

	if req.Verbose {
		debugInfo.WriteString(fmt.Sprintf("Execution completed in %dms\n", duration))
		resp.Debug = debugInfo.String()
	}

	return resp
}
