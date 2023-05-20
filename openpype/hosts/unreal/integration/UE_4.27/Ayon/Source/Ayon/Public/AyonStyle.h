// Copyright 2023, Ayon, All rights reserved.
#pragma once
#include "CoreMinimal.h"

class FSlateStyleSet;
class ISlateStyle;


class FAyonStyle
{
public:
	static void Initialize();
	static void Shutdown();
	static const ISlateStyle& Get();
	static FName GetStyleSetName();
	static FName GetContextName();

	static void SetIcon(const FString& StyleName, const FString& ResourcePath);

private:
	static TUniquePtr< FSlateStyleSet > Create();
	static TUniquePtr< FSlateStyleSet > AyonStyleInstance;
};