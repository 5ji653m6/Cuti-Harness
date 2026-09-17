"""
Integration tests for Suno API music generation
This test makes real API calls to Suno API service

To run this test:
    pytest tests/tools/test_suno_integration.py -v

This test requires:
    - Suno API key configured in suno_service
    - May consume Suno API credits
    - Takes several minutes to complete (music generation + polling)
"""
import pytest

# 直接导入核心实现函数（不包含 @tool 装饰器）
from app.tools.music.suno import _generate_music_with_suno_impl
from app.models.image_result import MusicProvider


# 标记为集成测试
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bgm_generation():
    """测试1：纯音乐BGM生成
    
    测试场景：生成背景音乐，不包含歌词
    """
    
    test_prompt = "A calm, cheerful piano melody suitable for children's story videos"
    
    print("\n" + "="*60)
    print("🎵 测试1：纯音乐BGM生成")
    print("="*60)
    print(f"📝 音乐描述: {test_prompt}")
    print(f"🎼 模式: 纯音乐BGM")
    print(f"🎯 has_lyrics=False")
    print("="*60 + "\n")
    
    # 调用音乐生成
    result = await _generate_music_with_suno_impl(
        prompt=test_prompt,
        has_lyrics=False
    )
    
    # 验证结果
    assert result.success is True, f"音乐生成失败: {result.error}"
    assert result.provider == MusicProvider.SUNO, "Provider should be Suno"
    assert result.clips, "Clips should not be empty"
    assert result.clips[0].audio_url, "Audio URL should not be empty"
    
    print(f"\n✅ 纯音乐BGM生成成功！")
    print(f"🎵 音频URL: {result.clips[0].audio_url}")
    print(f"🎵 Clips数量: {result.clips_count}")
    print(f"🎼 提供商: {result.provider}")
    print()


@pytest.mark.asyncio
async def test_song_with_lyrics_generation():
    """测试2：带歌词的歌曲生成
    
    测试场景：生成带有结构化歌词的歌曲
    """
    
    # 结构化歌词（包含 Verse 和 Chorus 标签）
    test_lyrics = """[Verse]
Today is a beautiful day
Let's go out and play
Sunshine fills the sky
Makes us feel so high

[Chorus]
Happy times together
Joy will last forever
Singing all day long
This is our song"""
    
    print("\n" + "="*60)
    print("🎵 测试2：带歌词歌曲生成")
    print("="*60)
    print(f"📝 结构化歌词:")
    print(test_lyrics)
    print(f"🎼 模式: 带歌词歌曲")
    print(f"🎯 has_lyrics=True")
    print("="*60 + "\n")
    
    # 调用音乐生成
    result = await _generate_music_with_suno_impl(
        prompt=test_lyrics,
        has_lyrics=True
    )
    
    # 验证结果
    assert result.success is True, f"音乐生成失败: {result.error}"
    assert result.provider == MusicProvider.SUNO, "Provider should be Suno"
    assert result.clips, "Clips should not be empty"
    assert result.clips[0].audio_url, "Audio URL should not be empty"
    
    print(f"\n✅ 带歌词歌曲生成成功！")
    print(f"🎵 音频URL: {result.clips[0].audio_url}")
    print(f"🎵 Clips数量: {result.clips_count}")
    print(f"🎵 歌词: {result.clips[0].lyrics}")
    print(f"🎼 提供商: {result.provider}")
    print()


@pytest.mark.asyncio
async def test_auto_lyrics_short_with_vocal_gender():
    """测试3：auto_lyrics 短曲 + vocal_gender='f'（排查 400 是否与 gender 相关）

    使用与报错场景一致的参数，验证带 vocal_gender 时是否触发 400。
    """
    prompt = (
        "upbeat bright rhythm, running on playground, energetic youthful vibe, "
        "positive uplifting mood, 30 seconds short version"
    )
    print("\n" + "=" * 60)
    print("🎵 测试3：auto_lyrics 短曲 + vocal_gender='f'")
    print("=" * 60)
    print(f"📝 prompt: {prompt}")
    print(f"🎯 has_lyrics=False, auto_lyrics=True, target_duration=30")
    print(f"🎯 tags='Short version', vocal_gender='f'")
    print("=" * 60 + "\n")

    result = await _generate_music_with_suno_impl(
        prompt=prompt,
        has_lyrics=False,
        auto_lyrics=True,
        target_duration=30,
        tags="Short version",
        vocal_gender="f",
    )

    assert result.success is True, f"音乐生成失败: {result.error}"
    assert result.provider == MusicProvider.SUNO
    assert result.clips
    assert result.clips[0].audio_url

    print(f"\n✅ auto_lyrics + vocal_gender='f' 生成成功")
    print(f"🎵 音频URL: {result.clips[0].audio_url}")
    print(f"🎵 Clips数量: {result.clips_count}\n")


@pytest.mark.asyncio
async def test_auto_lyrics_short_without_vocal_gender():
    """测试4：同上参数但不传 vocal_gender（对比：若测试3 失败而本测试通过，则 400 可能由 vocal_gender 引起）"""
    prompt = (
        "upbeat bright rhythm, running on playground, energetic youthful vibe, "
        "positive uplifting mood, 30 seconds short version"
    )
    print("\n" + "=" * 60)
    print("🎵 测试4：auto_lyrics 短曲，不传 vocal_gender")
    print("=" * 60)
    print(f"📝 prompt: {prompt}")
    print(f"🎯 vocal_gender=None（不传）")
    print("=" * 60 + "\n")

    result = await _generate_music_with_suno_impl(
        prompt=prompt,
        has_lyrics=False,
        auto_lyrics=True,
        target_duration=30,
        tags="Short version",
        vocal_gender=None,
    )

    assert result.success is True, f"音乐生成失败: {result.error}"
    assert result.provider == MusicProvider.SUNO
    assert result.clips
    assert result.clips[0].audio_url

    print(f"\n✅ auto_lyrics 无 vocal_gender 生成成功")
    print(f"🎵 音频URL: {result.clips[0].audio_url}")
    print(f"🎵 Clips数量: {result.clips_count}\n")

