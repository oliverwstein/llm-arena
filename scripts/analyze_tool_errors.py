#!/usr/bin/env python3
"""Analyze tool harness JSONL logs for tool-call errors."""
import json
import glob
import sys

LOG_DIR = "logs/llm-vs-llm-2026-02-07-1548/battles"

def analyze_tool_file(filepath):
    """Parse a tool-B.jsonl file and extract error-related info."""
    errors = []
    all_tool_calls = []
    with open(filepath) as f:
        for line_no, line in enumerate(f, 1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                errors.append({"line": line_no, "type": "json_parse_error", "detail": line[:200]})
                continue
            
            turn = entry.get("turn", "?")
            
            # Check tool_calls for actual error responses (containing {"error": ...})
            tool_calls = entry.get("tool_calls", [])
            for tc in tool_calls:
                tc_info = {
                    "turn": turn,
                    "name": tc.get("name"),
                    "args": tc.get("args"),
                    "result": tc.get("result"),
                }
                all_tool_calls.append(tc_info)
                
                result_str = tc.get("result", "")
                # Only count actual error responses (JSON with "error" key)
                try:
                    result_data = json.loads(result_str)
                    if isinstance(result_data, dict) and "error" in result_data:
                        error_msg = result_data["error"]
                        
                        # Categorize the error
                        if "not found in available moves" in error_msg:
                            error_type = "move_not_available"
                        elif "forced switch" in error_msg:
                            error_type = "forced_switch"
                        elif "not found" in error_msg:
                            error_type = "lookup_not_found"
                        elif "not seen" in error_msg:
                            error_type = "pokemon_not_seen"
                        elif "No active" in error_msg or "No opponent" in error_msg:
                            error_type = "no_active_pokemon"
                        elif "fainted" in error_msg:
                            error_type = "fainted_pokemon"
                        else:
                            error_type = "other_error"
                        
                        errors.append({
                            "turn": turn,
                            "type": error_type,
                            "tool_name": tc.get("name"),
                            "args": tc.get("args"),
                            "error_msg": error_msg,
                        })
                except (json.JSONDecodeError, TypeError):
                    pass
    
    return errors, all_tool_calls

def main():
    tool_files = sorted(glob.glob(f"{LOG_DIR}/*/Gemini-3-Fl-tool-B.jsonl"))
    
    print(f"Found {len(tool_files)} tool harness log files\n")
    
    grand_total_errors = []
    grand_total_calls = []
    
    for filepath in tool_files:
        battle = filepath.split("/")[-2]
        errors, all_calls = analyze_tool_file(filepath)
        grand_total_errors.extend(errors)
        grand_total_calls.extend(all_calls)
        
        print(f"=== {battle} ===")
        print(f"  Total tool calls: {len(all_calls)}")
        print(f"  Tool errors: {len(errors)}")
        
        for err in errors:
            print(f"\n  [Turn {err['turn']}] {err['type']}:")
            print(f"    Tool: {err['tool_name']}")
            print(f"    Args: {err['args']}")
            print(f"    Error: {err['error_msg']}")
        print()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print(f"Total tool calls across all battles: {len(grand_total_calls)}")
    print(f"Total tool errors across all battles: {len(grand_total_errors)}")
    if grand_total_calls:
        print(f"Error rate: {len(grand_total_errors)/len(grand_total_calls)*100:.1f}%")
    
    # Group errors by type
    print("\nErrors by category:")
    by_type = {}
    for err in grand_total_errors:
        t = err['type']
        by_type.setdefault(t, []).append(err)
    for t, errs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"  {t}: {len(errs)}")
    
    # Group by tool name
    print("\nErrors by tool:")
    by_tool = {}
    for err in grand_total_errors:
        tn = err['tool_name']
        by_tool.setdefault(tn, []).append(err)
    for tn, errs in sorted(by_tool.items(), key=lambda x: -len(x[1])):
        print(f"\n  {tn}: {len(errs)} errors")
        # Show unique error messages
        unique_msgs = {}
        for e in errs:
            msg = e['error_msg']
            unique_msgs.setdefault(msg, 0)
            unique_msgs[msg] += 1
        for msg, count in sorted(unique_msgs.items(), key=lambda x: -x[1]):
            print(f"    [{count}x] {msg}")
    
    # Tool usage summary
    print("\n\nTool usage summary:")
    tool_usage = {}
    for tc in grand_total_calls:
        tool_usage.setdefault(tc['name'], 0)
        tool_usage[tc['name']] += 1
    for name, count in sorted(tool_usage.items(), key=lambda x: -x[1]):
        err_count = len([e for e in grand_total_errors if e['tool_name'] == name])
        rate = f" ({err_count}/{count} = {err_count/count*100:.0f}% error)" if err_count else ""
        print(f"  {name}: {count} calls{rate}")

if __name__ == "__main__":
    main()
