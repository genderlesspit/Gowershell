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
	"unicode/utf16"
)

// Windows-specific imports
var (
	CREATE_NEW_CONSOLE uint32 = 0x00000010
)

type Request struct {
	Command       string `json:"command"`
	Type          string `json:"type,omitempty"`           // "cmd", "powershell", "wsl"
	Headless      bool   `json:"headless,omitempty"`       // true for headless, false for headed
	Verbose       bool   `json:"verbose,omitempty"`        // toggleable verbose logging
	PersistWindow bool   `json:"persist_window,omitempty"` // true to keep window open, false to close when done
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
		debugInfo.WriteString(fmt.Sprintf("Type: %s, Headless: %t, PersistWindow: %t\n", req.Type, req.Headless, req.PersistWindow))
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

	// Configure window visibility based on headless flag
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
				CreationFlags: CREATE_NEW_CONSOLE,
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

	// Process output with UTF-16 detection and decoding
	processedOutput := processOutput(output, req.Verbose, &debugInfo)

	resp := Response{
		Output:   strings.TrimSpace(processedOutput),
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

func processOutput(data []byte, verbose bool, debugInfo *strings.Builder) string {
	if len(data) == 0 {
		return ""
	}

	// Check if output might be UTF-16 encoded
	if isUTF16(data) {
		if verbose {
			debugInfo.WriteString("UTF-16 encoding detected, decoding...\n")
		}
		return decodeUTF16(data)
	}

	// Standard UTF-8 processing
	if verbose {
		debugInfo.WriteString("Using standard UTF-8 processing\n")
	}
	return string(data)
}

func isUTF16(data []byte) bool {
	// Check for UTF-16 BOM (Byte Order Mark)
	if len(data) >= 2 {
		// UTF-16 LE BOM: 0xFF 0xFE
		if data[0] == 0xFF && data[1] == 0xFE {
			return true
		}
		// UTF-16 BE BOM: 0xFE 0xFF
		if data[0] == 0xFE && data[1] == 0xFF {
			return true
		}
	}

	// Heuristic check: if data length is even and contains many null bytes
	// at even positions, it might be UTF-16 LE
	if len(data)%2 == 0 && len(data) > 10 {
		nullCount := 0
		for i := 1; i < len(data); i += 2 {
			if data[i] == 0 {
				nullCount++
			}
		}
		// If more than 30% of even positions are null, likely UTF-16 LE
		return float64(nullCount)/float64(len(data)/2) > 0.3
	}

	return false
}

func decodeUTF16(data []byte) string {
	// Handle BOM if present
	start := 0
	littleEndian := true

	if len(data) >= 2 {
		if data[0] == 0xFF && data[1] == 0xFE {
			// UTF-16 LE BOM
			start = 2
			littleEndian = true
		} else if data[0] == 0xFE && data[1] == 0xFF {
			// UTF-16 BE BOM
			start = 2
			littleEndian = false
		}
	}

	// Adjust data to remove BOM
	data = data[start:]

	// Check if data length is even (UTF-16 requires pairs of bytes)
	if len(data)%2 != 0 {
		return string(data) // fallback to regular string conversion
	}

	// Convert bytes to UTF-16 code units
	utf16Data := make([]uint16, len(data)/2)
	for i := 0; i < len(data)/2; i++ {
		if littleEndian {
			utf16Data[i] = uint16(data[i*2]) | (uint16(data[i*2+1]) << 8)
		} else {
			utf16Data[i] = uint16(data[i*2+1]) | (uint16(data[i*2]) << 8)
		}
	}

	// Decode UTF-16 to runes and convert to string
	runes := utf16.Decode(utf16Data)
	return string(runes)
}
