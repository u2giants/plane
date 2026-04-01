"""Deep analysis of comment types - what's actually in comments."""
import json
from pathlib import Path
from collections import Counter

SNAPSHOT_DIR = Path(".")

def main():
    comments = json.load(open("comments_sample_2298436_20260331_023108.json", encoding="utf-8", errors="replace"))
    
    # Categorize all comment parts
    plain_text_count = 0
    block_count = 0
    attachment_count = 0
    image_count = 0
    mention_count = 0
    tag_count = 0
    emoticon_count = 0
    
    sample_texts = []
    
    for task_data in comments:
        for comment in task_data.get("comments", []):
            for part in comment.get("comment", []):
                ctype = part.get("type")
                
                # Determine the actual type
                if ctype is None:
                    text = part.get("text", "")
                    if "block-id" in part.get("attributes", {}):
                        block_count += 1
                    elif text.strip():
                        plain_text_count += 1
                        if len(sample_texts) < 20:
                            sample_texts.append(text[:100])
                    else:
                        block_count += 1
                elif ctype == "attachment":
                    attachment_count += 1
                elif ctype == "image":
                    image_count += 1
                elif ctype in ("mention", "link_mention", "task_mention"):
                    mention_count += 1
                elif ctype == "tag":
                    tag_count += 1
                elif ctype == "emoticon":
                    emoticon_count += 1
                elif ctype == "bookmark":
                    tag_count += 1
    
    print("=" * 70)
    print("COMMENT CONTENT BREAKDOWN")
    print("=" * 70)
    print(f"\nTotal tasks with comments: {len(comments)}")
    print(f"\nComment parts breakdown:")
    print(f"  Plain text: {plain_text_count} (actual user text)")
    print(f"  Block/layout: {block_count} (formatting/newlines)")
    print(f"  Attachments: {attachment_count}")
    print(f"  Images: {image_count}")
    print(f"  Mentions: {mention_count}")
    print(f"  Tags: {tag_count}")
    print(f"  Emoticons: {emoticon_count}")
    
    print("\n" + "=" * 70)
    print("SAMPLE PLAIN TEXT COMMENTS")
    print("=" * 70)
    for i, text in enumerate(sample_texts[:10]):
        print(f"\n{i+1}. {text}")
    
    print("\n" + "=" * 70)
    print("KEY INSIGHT")
    print("=" * 70)
    print("""
The 703 'unknown' types were:
1. Block/newline elements - NOT user content
2. Plain text comments - YES, we ARE capturing text!

This means comments analysis can tell us:
✅ What users are saying (plain text captured)
✅ Who they're mentioning (@user)
✅ What files they're sharing (attachments captured)
✅ What images they're including
❌ NOT: Comment editing history (only latest captured)
❌ NOT: Comment reactions
❌ NOT: Thread replies (flat structure)

For workflow analysis:
- Comment count = team communication volume
- Attachments = evidence/documents shared
- Mentions = collaboration patterns
""")

if __name__ == "__main__":
    main()
